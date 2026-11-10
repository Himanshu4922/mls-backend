"""
Replace dead/missing DDF gallery URLs with live AMPRE (TRREB) MediaURLs.

Examples:
  python manage.py refresh_media_from_ampre --listing-id W12914842
  python manage.py refresh_media_from_ampre --missing --limit 500
  python manage.py refresh_media_from_ampre --dead-preferred --limit 0
  python manage.py refresh_media_from_ampre --all-active --limit 0
  python manage.py refresh_media_from_ampre --missing --include-inactive --limit 0
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Prefetch

from mls.models import Media, Property
from mls.services.ampre_client import AmpreClientError
from mls.services.ampre_media import (
    ALL_MEDIA_STATUSES,
    INACTIVE_STATUSES,
    is_trreb_property,
    refresh_property_media_from_ampre,
    url_ok,
)


class Command(BaseCommand):
    help = (
        "Refresh listing gallery URLs from AMPRE for dead DDF CDN links "
        "and TRREB listings with no media rows (Active and optionally "
        "sold / de-listed)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--listing-id",
            action="append",
            dest="listing_ids",
            default=[],
            help="MLS number (listing_id), repeatable.",
        )
        parser.add_argument(
            "--listing-key",
            action="append",
            dest="listing_keys",
            default=[],
            help="Internal listing_key, repeatable.",
        )
        parser.add_argument(
            "--dead-preferred",
            action="store_true",
            help="Scan listings whose preferred non-AMPRE photo 404s.",
        )
        parser.add_argument(
            "--missing",
            action="store_true",
            help="Backfill TRREB listings that have zero media rows.",
        )
        parser.add_argument(
            "--all-active",
            action="store_true",
            help="Equivalent to --missing plus --dead-preferred (Active only).",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help=(
                "Also include Closed/Sold/Expired/Cancelled/Withdrawn listings. "
                "Needed for Sold and De-listed tabs that sync without DDF media."
            ),
        )
        parser.add_argument(
            "--inactive-only",
            action="store_true",
            help="Only Closed/Sold/Expired/Cancelled/Withdrawn (skip Active).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=200,
            help="Max listings to repair (0 = no limit). Default 200.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Refresh from AMPRE even if the current preferred URL is healthy.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and report without writing.",
        )

    def _statuses(self, options) -> list[str]:
        if options["inactive_only"]:
            return list(INACTIVE_STATUSES)
        if options["include_inactive"]:
            return list(ALL_MEDIA_STATUSES)
        return ["Active"]

    def handle(self, *args, **options):
        if options["all_active"]:
            options["missing"] = True
            options["dead_preferred"] = True

        limit = options["limit"]
        unlimited = limit == 0
        cap = None if unlimited else max(1, limit)
        statuses = self._statuses(options)

        targets: list[Property] = []
        listing_ids = options["listing_ids"] or []
        listing_keys = options["listing_keys"] or []

        if listing_ids:
            targets.extend(list(Property.objects.filter(listing_id__in=listing_ids)))
        if listing_keys:
            targets.extend(list(Property.objects.filter(listing_key__in=listing_keys)))
        if options["missing"]:
            targets.extend(self._find_missing(cap, statuses))
        if options["dead_preferred"]:
            # When both missing and dead are requested, spend remaining budget
            # on dead preferred after missing.
            remaining = None
            if cap is not None:
                remaining = max(0, cap - len({p.pk for p in targets}))
            if remaining is None or remaining > 0:
                targets.extend(
                    self._find_dead_preferred(
                        remaining if remaining is not None else 10_000,
                        statuses,
                    )
                )

        seen: set[int] = set()
        unique_targets: list[Property] = []
        for prop in targets:
            if prop.pk in seen:
                continue
            seen.add(prop.pk)
            unique_targets.append(prop)
            if cap is not None and len(unique_targets) >= cap:
                break

        if not unique_targets:
            raise CommandError(
                "No properties selected. Pass --listing-id / --listing-key, "
                "--missing, --dead-preferred, or --all-active "
                "(optionally with --include-inactive / --inactive-only)."
            )

        repaired = 0
        for index, prop in enumerate(unique_targets, start=1):
            listing_id = (prop.listing_id or "").strip()
            label = (
                f"{listing_id or prop.listing_key} "
                f"[{prop.standard_status or '?'}] "
                f"({prop.unparsed_address or prop.listing_key})"
            )
            if not is_trreb_property(prop):
                self.stdout.write(
                    self.style.WARNING(f"Skip {label}: not a TRREB-style MLS id")
                )
                continue

            if not options["force"]:
                preferred = (
                    prop.media.filter(is_preferred=True).order_by("order", "pk").first()
                    or prop.media.order_by("order", "pk").first()
                )
                if (
                    preferred
                    and preferred.media_url
                    and "ampre.ca" in preferred.media_url
                    and url_ok(preferred.media_url)
                ):
                    self.stdout.write(f"{label}: already on healthy AMPRE URL")
                    continue

            if options["dry_run"]:
                self.stdout.write(f"DRY-RUN [{index}/{len(unique_targets)}] {label}")
                continue

            try:
                count = refresh_property_media_from_ampre(prop)
            except AmpreClientError as exc:
                self.stdout.write(self.style.ERROR(f"{label}: {exc}"))
                continue

            if count:
                repaired += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{index}/{len(unique_targets)}] {label}: wrote {count} photos"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"[{index}/{len(unique_targets)}] {label}: no AMPRE photos written"
                    )
                )

        self.stdout.write(self.style.NOTICE(f"Repaired {repaired} listing(s)."))

    def _find_missing(self, limit: int | None, statuses: list[str]) -> list[Property]:
        qs = (
            Property.objects.filter(standard_status__in=statuses)
            .exclude(listing_id="")
            .annotate(media_count=Count("media"))
            .filter(media_count=0)
            .order_by("id")
        )
        out: list[Property] = []
        for prop in qs.iterator(chunk_size=500):
            if not is_trreb_property(prop):
                continue
            out.append(prop)
            if limit is not None and len(out) >= limit:
                break
        return out

    def _find_dead_preferred(self, limit: int, statuses: list[str]) -> list[Property]:
        qs = (
            Property.objects.filter(standard_status__in=statuses)
            .exclude(listing_id="")
            .filter(
                media__is_preferred=True,
            )
            .exclude(media__media_url__icontains="ampre.ca")
            .prefetch_related(
                Prefetch(
                    "media",
                    queryset=Media.objects.filter(is_preferred=True).order_by(
                        "order", "pk"
                    ),
                    to_attr="preferred_media",
                )
            )
            .order_by("-photos_count", "id")
            .distinct()
        )

        # Probe more than we need; many preferred URLs are still healthy.
        probe_budget = max(limit * 4, 200) if limit else 20_000
        candidates: list[tuple[Property, str]] = []
        for prop in qs[:probe_budget]:
            if not is_trreb_property(prop):
                continue
            preferred = (getattr(prop, "preferred_media", None) or [None])[0]
            if preferred is None:
                preferred = (
                    prop.media.filter(is_preferred=True).order_by("order", "pk").first()
                )
            if not preferred or not preferred.media_url:
                continue
            candidates.append((prop, preferred.media_url))

        dead: list[Property] = []
        with ThreadPoolExecutor(max_workers=24) as pool:
            futures = {
                pool.submit(url_ok, url): prop for prop, url in candidates
            }
            for future in as_completed(futures):
                prop = futures[future]
                if not future.result():
                    dead.append(prop)
                    if limit and len(dead) >= limit:
                        break
        return dead[:limit] if limit else dead
