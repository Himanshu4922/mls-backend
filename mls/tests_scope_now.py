"""Assistant, pre-con activity, push storage and CRM lead tagging."""

import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from mls.models import Content, PreconActivityEvent, PropertyInquiry
from mls.services.ai_assist import _safe_href
from mls.services.inquiry_ghl import _inquiry_tags
from mls.services.lead_ghl import push_lead_to_ghl


def _project(title="Harbour Tower"):
    content = Content.objects.create(
        wp_id=Content.objects.count() + 90_000,
        content_type=Content.PROPERTY,
        title=title,
        slug=f"harbour-{Content.objects.count()}",
        status=Content.PUBLISH,
    )
    # A post_save signal creates the PreComProperty row.
    return content.property


class AssistTests(TestCase):
    def test_rejects_an_empty_question(self):
        response = APIClient().post("/api/mls/ai/assist/", {"question": "  "}, format="json")
        self.assertEqual(response.status_code, 400)

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""})
    def test_fallback_links_stay_on_this_site(self):
        response = APIClient().post(
            "/api/mls/ai/assist/",
            {"question": "Show me assignments in Vaughan"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["fallback"])
        self.assertTrue(body["links"])
        self.assertTrue(all(link["href"].startswith("/") for link in body["links"]))

    def test_drops_external_links(self):
        self.assertIsNone(_safe_href("https://example.com/listings"))
        self.assertEqual(_safe_href("/listings?city=Vaughan"), "/listings?city=Vaughan")


class PreconActivityTests(TestCase):
    def test_records_a_page_view(self):
        project = _project()
        response = APIClient().post(
            "/api/mls/activity/precon/",
            {"project_id": project.pk, "event": "floor_plans", "session_key": "abc"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(PreconActivityEvent.objects.filter(project=project, event="floor_plans").count(), 1)

    def test_studio_report_is_staff_only(self):
        guest = APIClient().get("/api/mls/studio/activity/")
        self.assertIn(guest.status_code, {401, 403})

        staff = get_user_model().objects.create_user(
            email="staff-activity@example.com",
            password="safe-password-123",
            is_staff=True,
            is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=staff)
        report = client.get("/api/mls/studio/activity/")
        self.assertEqual(report.status_code, 200)
        self.assertIn("top_projects", report.json())


class PushAndCrmTests(TestCase):
    def test_push_subscribe_requires_sign_in(self):
        response = APIClient().post(
            "/api/mls/push/subscribe/",
            {"endpoint": "https://push.example/1", "keys": {"p256dh": "k", "auth": "a"}},
            format="json",
        )
        self.assertIn(response.status_code, {401, 403})

    @override_settings(GHL_API_KEY="", GHL_LOCATION_ID="")
    def test_crm_push_is_a_no_op_without_keys(self):
        push_lead_to_ghl(
            email="lead@example.com",
            source="newsletter",
            tags=["newsletter"],
            note="Newsletter sign-up",
        )

    def test_market_and_assignment_inquiries_are_tagged(self):
        market = PropertyInquiry(
            first_name="A",
            email="a@example.com",
            message="hello",
            page_url="https://homeatlas.test/market-trends",
            intent="explore",
        )
        assignment = PropertyInquiry(
            first_name="A",
            email="a@example.com",
            message="hello",
            listing_key="ASSIGNMENT-4",
            page_url="https://homeatlas.test/assignments/4",
        )
        self.assertIn("market-trends", _inquiry_tags(market))
        self.assertIn("assignment-inquiry", _inquiry_tags(assignment))
