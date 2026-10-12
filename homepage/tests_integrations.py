import os

from django.test import TestCase

from homepage.runtime_config import invalidate, public_payload, save_values, stored_values


class IntegrationSettingsTests(TestCase):
    def tearDown(self):
        os.environ.pop("SENDGRID_API_KEY", None)
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        invalidate()

    def test_blank_secret_is_kept_and_hidden_from_the_public_site(self):
        save_values({"sendgridApiKey": "secret-value", "googleClientId": "google-id"})
        save_values({"sendgridApiKey": "  "})
        self.assertEqual(stored_values()["sendgridApiKey"], "secret-value")
        payload = public_payload()
        self.assertEqual(payload["googleClientId"], "google-id")
        self.assertNotIn("sendgridApiKey", payload)

    def test_clear_removes_a_saved_secret(self):
        save_values({"sendgridApiKey": "secret-value"})
        save_values({}, ["sendgridApiKey"])
        self.assertNotIn("sendgridApiKey", stored_values())
