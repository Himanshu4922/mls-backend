"""Sold-trends chunking, cache fallback and request metadata.

SimpleTestCase only: none of this touches the database, and AMPRE is mocked.
"""
from datetime import datetime, timezone as dt_timezone
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.test.client import RequestFactory

from mls import views_market
from mls.services.ampre_client import AmpreClientError
from mls.services.request_meta import client_ip, user_agent

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "sold-trends-tests"}}


class MonthRangesTests(SimpleTestCase):
    def test_ranges_are_contiguous_and_cover_the_window(self):
        now = datetime(2026, 9, 25, 12, tzinfo=dt_timezone.utc)
        ranges = views_market._month_ranges(12, now)
        self.assertEqual(ranges[0][0], "2025-09-18")  # 12 * 31 = 372 days back
        self.assertEqual(ranges[-1][1], "2026-09-26")  # tomorrow, exclusive
        for (_, end), (start, _) in zip(ranges, ranges[1:]):
            self.assertEqual(end, start)
        # Every boundary after the first is the 1st of a month.
        self.assertTrue(all(start.endswith("-01") for start, _ in ranges[1:]))

    def test_year_rollover(self):
        now = datetime(2026, 1, 10, tzinfo=dt_timezone.utc)
        starts = [start for start, _ in views_market._month_ranges(2, now)]
        self.assertIn("2025-12-01", starts)
        self.assertIn("2026-01-01", starts)


class SoldFilterTests(SimpleTestCase):
    def test_quotes_are_escaped_and_subtypes_ored(self):
        expr = views_market._sold_filter("King's Town", "2026-01-01", "2026-02-01", ["Detached", "Semi-Detached"])
        self.assertIn("startswith(City,'King''s Town')", expr)
        self.assertIn("CloseDate lt 2026-02-01", expr)
        self.assertIn("(PropertySubType eq 'Detached' or PropertySubType eq 'Semi-Detached')", expr)

    def test_fetch_queries_every_city_month_chunk(self):
        with mock.patch.object(views_market, "fetch_property_page", return_value=[{"ListingKey": "x"}]) as fetch:
            rows = views_market._fetch_sold_rows(["Toronto", "Brampton"], 2)
        chunks = len(views_market._month_ranges(2, views_market.timezone.now()))
        self.assertEqual(fetch.call_count, 2 * chunks)
        self.assertEqual(len(rows), 2 * chunks)

    def test_one_failed_chunk_fails_the_fetch(self):
        with mock.patch.object(views_market, "fetch_property_page", side_effect=AmpreClientError("boom")):
            with self.assertRaises(AmpreClientError):
                views_market._fetch_sold_rows(["Toronto"], 1)


@override_settings(CACHES=LOCMEM)
class GetSoldTrendsCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_serves_fresh_cache_without_refetching(self):
        with mock.patch.object(views_market, "build_sold_trends_payload", return_value={"series": [], "stale": False}) as build:
            views_market.get_sold_trends(["Toronto"], 12)
            views_market.get_sold_trends(["Toronto"], 12)
        self.assertEqual(build.call_count, 1)

    def test_falls_back_to_last_good_copy_when_upstream_fails(self):
        with mock.patch.object(views_market, "build_sold_trends_payload", return_value={"series": [1], "stale": False}):
            views_market.get_sold_trends(["Toronto"], 12)
        with mock.patch.object(views_market, "build_sold_trends_payload", side_effect=AmpreClientError("down")):
            payload = views_market.get_sold_trends(["Toronto"], 12, force_refresh=True)
        self.assertEqual(payload["series"], [1])
        self.assertTrue(payload["stale"])

    def test_raises_when_nothing_cached_and_upstream_fails(self):
        with mock.patch.object(views_market, "build_sold_trends_payload", side_effect=AmpreClientError("down")):
            with self.assertRaises(AmpreClientError):
                views_market.get_sold_trends(["Toronto"], 12)

    def test_property_types_get_their_own_cache_entry(self):
        a = views_market._sold_trends_cache_keys(["Toronto"], 12, "", None)
        b = views_market._sold_trends_cache_keys(["Toronto"], 12, "", ["Detached"])
        self.assertNotEqual(a, b)

    def test_warm_reports_failures_and_continues(self):
        def fake(cities, window, scope="", property_sub_types=None, force_refresh=False):
            if cities == ["Toronto"]:
                raise AmpreClientError("slow")
            return {}

        with mock.patch.object(views_market, "get_sold_trends", side_effect=fake):
            report = views_market.warm_sold_trends()
        self.assertIn("Toronto", report["failed"])
        self.assertIn("gta", report["ok"])
        self.assertEqual(len(report["ok"]), len(views_market.SOLD_TRENDS_WARM_CITIES))


class RequestMetaTests(SimpleTestCase):
    def test_first_forwarded_address_wins(self):
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1", REMOTE_ADDR="10.0.0.2")
        self.assertEqual(client_ip(request), "203.0.113.7")

    def test_falls_back_to_remote_addr(self):
        request = RequestFactory().get("/", REMOTE_ADDR="198.51.100.4")
        self.assertEqual(client_ip(request), "198.51.100.4")

    def test_user_agent_is_truncated(self):
        request = RequestFactory().get("/", HTTP_USER_AGENT="x" * 2000)
        self.assertEqual(len(user_agent(request)), 512)
