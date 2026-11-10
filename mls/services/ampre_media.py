"""Refresh listing gallery URLs from AMPRE when DDF CDN links are dead.

TRREB photos are mirrored on ``trreb-image.ampre.ca``. CREA DDF often keeps
serving ``ddfcdn.realtor.ca`` paths that later 404, which makes every gallery
tile fall back to the house placeholder while ``photos_count`` stays correct.

Sold / de-listed rows from ``sync_ampre_closed`` also often arrive with zero
media rows; the same AMPRE Media endpoint backfills those galleries.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable
from urllib.request import Request, urlopen

from django.db import transaction

from mls.models import Media, Property
from mls.services.ampre_client import AmpreClientError, fetch_media_page

logger = logging.getLogger(__name__)

SIZE_SUFFIX_RE = re.compile(r"-(?:l|m|t|nw)$", re.I)
VARIANT_RANK = {"l": 0, "": 1, "m": 2, "nw": 3, "t": 4}
PHOTO_CATEGORIES = {"", "photo", "property photo"}
# Board MLS numbers on AMPRE / TRREB (W12914842, E12899528, ...).
TRREB_LISTING_ID_RE = re.compile(r"^[A-Z]\d{5,}$")
# Sold / de-listed rows come from sync_ampre_closed without DDF Media.
INACTIVE_STATUSES = (
    "Closed",
    "Sold",
    "Expired",
    "Canceled",
    "Cancelled",
    "Withdrawn",
)
ALL_MEDIA_STATUSES = ("Active",) + INACTIVE_STATUSES


def _trreb_keys_for(prop: Property) -> list[str]:
    """AMPRE Media.ResourceRecordKey may be ListingId or ListingKey."""
    keys: list[str] = []
    for candidate in (
        (prop.listing_id or "").strip(),
        (prop.listing_key or "").strip(),
    ):
        if candidate and candidate not in keys:
            keys.append(candidate)
    return keys


def is_trreb_property(prop: Property) -> bool:
    return any(TRREB_LISTING_ID_RE.match(key) for key in _trreb_keys_for(prop))


def _variant_of(media_key: str) -> tuple[str, str]:
    key = (media_key or "").strip()
    match = SIZE_SUFFIX_RE.search(key)
    if not match:
        return key, ""
    return key[: match.start()], match.group(0)[1:].lower()


def _is_photo_row(row: dict[str, Any]) -> bool:
    category = str(row.get("MediaCategory") or "").strip().lower()
    url = str(row.get("MediaURL") or "").strip().lower()
    if category in PHOTO_CATEGORIES:
        return bool(url)
    return url.endswith((".jpg", ".jpeg", ".png", ".webp"))


def dedupe_ampre_photos(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for row in rows:
        if not _is_photo_row(row):
            continue
        url = (row.get("MediaURL") or "").strip()
        key = (row.get("MediaKey") or "").strip()
        if not url or not key:
            continue
        base, variant = _variant_of(key)
        if variant in {"t", "nw"}:
            continue
        rank = VARIANT_RANK.get(variant, 99)
        previous = best.get(base)
        if previous is None or rank < previous[0]:
            best[base] = (rank, row)

    selected = [item[1] for item in best.values()]
    selected.sort(
        key=lambda row: (
            0 if row.get("PreferredPhotoYN") else 1,
            row.get("Order") if isinstance(row.get("Order"), int) else 999,
            row.get("MediaKey") or "",
        )
    )
    unique: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in selected:
        url = (row.get("MediaURL") or "").strip()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        unique.append(row)
    return unique


def url_ok(url: str, timeout: float = 12) -> bool:
    try:
        request = Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=timeout) as response:
            response.read(32)
            return response.status == 200
    except Exception:
        return False


def replace_property_media(prop: Property, photos: list[dict[str, Any]]) -> int:
    with transaction.atomic():
        Media.objects.filter(property_id=prop.id).delete()
        rows: list[Media] = []
        for index, photo in enumerate(photos, start=1):
            order = photo.get("Order") if isinstance(photo.get("Order"), int) else index
            rows.append(
                Media(
                    property=prop,
                    media_url=photo["MediaURL"],
                    media_category=photo.get("MediaCategory") or "Photo",
                    is_preferred=bool(photo.get("PreferredPhotoYN")),
                    order=order,
                )
            )
        if rows and not any(row.is_preferred for row in rows):
            rows[0].is_preferred = True
        Media.objects.bulk_create(rows)
        Property.objects.filter(pk=prop.pk).update(photos_count=len(rows))
    return len(rows)


def fetch_ampre_photos_for_listing_id(listing_id: str) -> list[dict[str, Any]]:
    raw = fetch_media_page(
        filter_expression=f"ResourceRecordKey eq '{listing_id}'",
        select_fields=[
            "MediaURL",
            "MediaKey",
            "Order",
            "PreferredPhotoYN",
            "MediaCategory",
        ],
        orderby="Order",
        top=200,
        max_rows=500,
    )
    return dedupe_ampre_photos(raw)


def refresh_property_media_from_ampre(prop: Property) -> int:
    keys = _trreb_keys_for(prop)
    if not keys:
        return 0
    photos: list[dict[str, Any]] = []
    used_key = keys[0]
    for key in keys:
        photos = fetch_ampre_photos_for_listing_id(key)
        if photos:
            used_key = key
            break
    if not photos:
        return 0
    if not url_ok(photos[0]["MediaURL"]):
        logger.warning(
            "AMPRE media for %s failed health check; leaving existing rows",
            used_key,
        )
        return 0
    return replace_property_media(prop, photos)


def _needs_ampre_refresh(prop: Property, *, only_if_dead: bool) -> bool:
    if not is_trreb_property(prop):
        return False

    preferred = (
        prop.media.filter(is_preferred=True).order_by("order", "pk").first()
        or prop.media.order_by("order", "pk").first()
    )
    # No gallery rows at all — common for DDF imports that omitted Media
    # and for Closed/Expired rows upserted by sync_ampre_closed.
    if preferred is None:
        return True
    if not only_if_dead:
        return True
    if preferred.media_url and url_ok(preferred.media_url):
        return False
    if preferred.media_url and "ampre.ca" in preferred.media_url:
        # Already on AMPRE; leave alone even if the health check flaked.
        return False
    return True


def repair_dead_ddf_media(
    properties: Iterable[Property],
    *,
    only_if_dead: bool = True,
) -> int:
    """Replace/backfill gallery rows from AMPRE for TRREB listings.

    Covers both dead ``ddfcdn`` URLs and listings that have zero media rows.
    Returns the number of properties whose media was rewritten.
    """
    repaired = 0
    for prop in properties:
        label = (prop.listing_id or prop.listing_key or "").strip()
        if not _needs_ampre_refresh(prop, only_if_dead=only_if_dead):
            continue

        try:
            written = refresh_property_media_from_ampre(prop)
        except AmpreClientError as exc:
            logger.warning("AMPRE media refresh failed for %s: %s", label, exc)
            continue
        if written:
            repaired += 1
            logger.info(
                "Refreshed %s media rows for %s from AMPRE",
                written,
                label,
            )
    return repaired


def iter_trreb_needing_media(
    *,
    missing_only: bool = False,
    statuses: Iterable[str] | None = None,
) -> list[Property]:
    """TRREB listings that need an AMPRE gallery refresh."""
    status_list = list(statuses) if statuses is not None else ["Active"]
    qs = (
        Property.objects.filter(standard_status__in=status_list)
        .exclude(listing_id="")
        .order_by("id")
    )
    # Narrow in Python with the same board-id rule the sync uses; SQL regex
    # dialects differ between Postgres and SQLite test runs.
    out: list[Property] = []
    for prop in qs.iterator(chunk_size=500):
        if not is_trreb_property(prop):
            continue
        has_media = prop.media.exists()
        if missing_only and has_media:
            continue
        out.append(prop)
    return out


def iter_active_trreb_needing_media(*, missing_only: bool = False) -> list[Property]:
    """Active TRREB listings that need an AMPRE gallery refresh."""
    return iter_trreb_needing_media(missing_only=missing_only, statuses=["Active"])
