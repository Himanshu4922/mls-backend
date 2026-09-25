from django.core.management.base import BaseCommand

from mls.views_market import warm_sold_trends


class Command(BaseCommand):
    help = (
        "Rebuild the cached Market Trends sold data (each site city + GTA) from AMPRE. "
        "Run every few hours from celery beat or cron; needs a shared cache (CACHE_URL)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--window", type=int, default=12, help="Window in months (default 12).")

    def handle(self, *args, **options):
        report = warm_sold_trends(window_months=options["window"])
        self.stdout.write(self.style.SUCCESS(f"Warmed: {', '.join(report['ok']) or 'none'}"))
        for label, error in report["failed"].items():
            self.stderr.write(f"Failed {label}: {error}")
