"""Connection values saved in the admin console, with env as the fallback.

The public site only receives the fields marked public. A saved value replaces
the server environment until it is cleared.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

# key, env name, django setting attribute or "", public, secret, group, label, hint
FIELDS: tuple[dict, ...] = (
    {"key": "whatsappNumber", "env": "NEXT_PUBLIC_WHATSAPP_NUMBER", "setting": "", "public": True, "secret": False, "group": "Website", "label": "WhatsApp number", "hint": "Digits with the country code, such as 14168214200. Buttons use this number."},
    {"key": "siteUrl", "env": "NEXT_PUBLIC_SITE_URL", "setting": "", "public": True, "secret": False, "group": "Website", "label": "Website address", "hint": "The public site address, such as https://mls-xi-rouge.vercel.app."},
    {"key": "gaMeasurementId", "env": "NEXT_PUBLIC_GA_MEASUREMENT_ID", "setting": "", "public": True, "secret": False, "group": "Website", "label": "Google Analytics ID", "hint": "Loads only after a visitor accepts cookies. Leave blank to keep analytics off."},
    {"key": "metaPixelId", "env": "NEXT_PUBLIC_META_PIXEL_ID", "setting": "", "public": True, "secret": False, "group": "Website", "label": "Meta Pixel ID", "hint": "Loads only after a visitor accepts cookies."},
    {"key": "googleAdsId", "env": "NEXT_PUBLIC_GOOGLE_ADS_ID", "setting": "", "public": True, "secret": False, "group": "Website", "label": "Google Ads ID", "hint": "Loads only after a visitor accepts cookies."},
    {"key": "googleClientId", "env": "GOOGLE_CLIENT_ID", "setting": "GOOGLE_CLIENT_ID", "public": True, "secret": False, "group": "Sign-in", "label": "Google sign-in ID", "hint": "The same ID goes on the website and the server."},
    {"key": "googleClientSecret", "env": "GOOGLE_CLIENT_SECRET", "setting": "GOOGLE_CLIENT_SECRET", "public": False, "secret": True, "group": "Sign-in", "label": "Google sign-in secret", "hint": "From Google Cloud. Leave blank to keep the current secret."},
    {"key": "facebookAppId", "env": "FACEBOOK_APP_ID", "setting": "FACEBOOK_APP_ID", "public": True, "secret": False, "group": "Sign-in", "label": "Facebook app ID", "hint": "Shown on the sign-in button. Leave blank to hide Facebook sign-in."},
    {"key": "facebookAppSecret", "env": "FACEBOOK_APP_SECRET", "setting": "FACEBOOK_APP_SECRET", "public": False, "secret": True, "group": "Sign-in", "label": "Facebook app secret", "hint": "Leave blank to keep the current secret."},
    {"key": "facebookGraphVersion", "env": "FACEBOOK_GRAPH_VERSION", "setting": "FACEBOOK_GRAPH_VERSION", "public": True, "secret": False, "group": "Sign-in", "label": "Facebook version", "hint": "Usually v19.0."},
    {"key": "facebookRedirectUri", "env": "FACEBOOK_REDIRECT_URI", "setting": "FACEBOOK_REDIRECT_URI", "public": False, "secret": False, "group": "Sign-in", "label": "Facebook return address", "hint": "https://mls-xi-rouge.vercel.app/api/auth/facebook/callback"},
    {"key": "facebookAllowedRedirectUris", "env": "FACEBOOK_ALLOWED_REDIRECT_URIS", "setting": "FACEBOOK_ALLOWED_REDIRECT_URIS", "public": False, "secret": False, "group": "Sign-in", "label": "Extra Facebook return addresses", "hint": "Comma-separated, if staging and production both sign in."},
    {"key": "sendgridApiKey", "env": "SENDGRID_API_KEY", "setting": "SENDGRID_API_KEY", "public": False, "secret": True, "group": "Email", "label": "SendGrid key", "hint": "Sends verification mail, alerts, and lead notices."},
    {"key": "defaultFromEmail", "env": "DEFAULT_FROM_EMAIL", "setting": "DEFAULT_FROM_EMAIL", "public": False, "secret": False, "group": "Email", "label": "From address", "hint": "The address mail is sent from. The domain must be verified in SendGrid."},
    {"key": "realtorInboxEmail", "env": "REALTOR_INBOX_EMAIL", "setting": "REALTOR_INBOX_EMAIL", "public": False, "secret": False, "group": "Email", "label": "Lead inbox", "hint": "Where inquiry emails are delivered."},
    {"key": "frontendUrl", "env": "FRONTEND_URL", "setting": "FRONTEND_URL", "public": False, "secret": False, "group": "Email", "label": "Links in email", "hint": "The site address used inside verification and alert emails."},
    {"key": "newsletterSiteUrl", "env": "NEWSLETTER_SITE_URL", "setting": "", "public": False, "secret": False, "group": "Email", "label": "Newsletter site address", "hint": "Links inside the newsletter."},
    {"key": "ghlApiKey", "env": "GHL_API_KEY", "setting": "GHL_API_KEY", "public": False, "secret": True, "group": "CRM", "label": "GoHighLevel key", "hint": "Private integration token."},
    {"key": "ghlLocationId", "env": "GHL_LOCATION_ID", "setting": "GHL_LOCATION_ID", "public": False, "secret": False, "group": "CRM", "label": "GoHighLevel location", "hint": "The location this site writes contacts into."},
    {"key": "ghlUserId", "env": "GHL_USER_ID", "setting": "GHL_USER_ID", "public": False, "secret": False, "group": "CRM", "label": "GoHighLevel user", "hint": "The user attached to new notes."},
    {"key": "twilioAccountSid", "env": "TWILIO_ACCOUNT_SID", "setting": "TWILIO_ACCOUNT_SID", "public": False, "secret": False, "group": "Phone verification", "label": "Twilio account SID", "hint": "Starts with AC."},
    {"key": "twilioAuthToken", "env": "TWILIO_AUTH_TOKEN", "setting": "TWILIO_AUTH_TOKEN", "public": False, "secret": True, "group": "Phone verification", "label": "Twilio auth token", "hint": "Leave blank to keep the current token."},
    {"key": "twilioVerifyServiceSid", "env": "TWILIO_VERIFY_SERVICE_SID", "setting": "TWILIO_VERIFY_SERVICE_SID", "public": False, "secret": False, "group": "Phone verification", "label": "Twilio Verify service", "hint": "Starts with VA."},
    {"key": "openaiApiKey", "env": "OPENAI_API_KEY", "setting": "", "public": False, "secret": True, "group": "AI", "label": "OpenAI key", "hint": "AI search, listing summaries, and the assistant."},
    {"key": "cloudinaryCloudName", "env": "CLOUDINARY_CLOUD_NAME", "setting": "", "public": False, "secret": False, "group": "Photos", "label": "Cloudinary cloud name", "hint": "Where uploaded photos and files are stored."},
    {"key": "cloudinaryApiKey", "env": "CLOUDINARY_API_KEY", "setting": "", "public": False, "secret": False, "group": "Photos", "label": "Cloudinary API key", "hint": ""},
    {"key": "cloudinaryApiSecret", "env": "CLOUDINARY_API_SECRET", "setting": "", "public": False, "secret": True, "group": "Photos", "label": "Cloudinary API secret", "hint": "Leave blank to keep the current secret."},
    {"key": "ddfClientId", "env": "DDF_CLIENT_ID", "setting": "CLIENT_ID", "public": False, "secret": False, "group": "Listings", "label": "Listing feed ID", "hint": "CREA DDF client ID. Used when listings are synced."},
    {"key": "ddfClientSecret", "env": "DDF_CLIENT_SECRET", "setting": "CLIENT_SECRET", "public": False, "secret": True, "group": "Listings", "label": "Listing feed secret", "hint": "CREA DDF client secret."},
    {"key": "ampreBaseUrl", "env": "AMPRE_ODATA_BASE_URL", "setting": "AMPRE_ODATA_BASE_URL", "public": False, "secret": False, "group": "Market trends", "label": "Sold-data address", "hint": "Usually https://query.ampre.ca/odata."},
    {"key": "ampreBearerToken", "env": "AMPRE_ODATA_BEARER_TOKEN", "setting": "AMPRE_ODATA_BEARER_TOKEN", "public": False, "secret": True, "group": "Market trends", "label": "Sold-data token", "hint": "TRREB / AMPRE token. Market trends read sold prices with this."},
    {"key": "webPushPublicKey", "env": "WEB_PUSH_VAPID_PUBLIC_KEY", "setting": "", "public": False, "secret": False, "group": "Browser alerts", "label": "Push public key", "hint": "From a VAPID key pair."},
    {"key": "webPushPrivateKey", "env": "WEB_PUSH_VAPID_PRIVATE_KEY", "setting": "", "public": False, "secret": True, "group": "Browser alerts", "label": "Push private key", "hint": "Leave blank to keep the current key."},
    {"key": "webPushSubject", "env": "WEB_PUSH_VAPID_SUBJECT", "setting": "", "public": False, "secret": False, "group": "Browser alerts", "label": "Push contact", "hint": "A mailto: address, such as mailto:info@estate-4u.com."},
    {"key": "cacheUrl", "env": "CACHE_URL", "setting": "", "public": False, "secret": True, "group": "Advanced", "label": "Shared cache address", "hint": "Redis address. The server picks this up the next time it starts."},
)

_BY_KEY = {field["key"]: field for field in FIELDS}
_CACHE: dict = {"at": 0.0, "values": {}}
_TTL = 15.0


def field_keys() -> set[str]:
    return set(_BY_KEY)


def stored_values() -> dict[str, str]:
    now = time.monotonic()
    if now - _CACHE["at"] < _TTL:
        return _CACHE["values"]
    values: dict[str, str] = {}
    try:
        from homepage.models import IntegrationSettings

        row = IntegrationSettings.objects.order_by("id").first()
        raw = row.values if row and isinstance(row.values, dict) else {}
        for key in _BY_KEY:
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                values[key] = value.strip()
    except (OperationalError, ProgrammingError):
        values = {}
    _CACHE["at"] = now
    _CACHE["values"] = values
    return values


def invalidate() -> None:
    _CACHE["at"] = 0.0
    _CACHE["values"] = {}


def effective(key: str) -> str:
    stored = stored_values().get(key, "")
    if stored:
        return stored
    import os

    return os.environ.get(_BY_KEY[key]["env"], "").strip()


def apply_overlay() -> None:
    """Copy saved values onto the process so existing settings reads pick them up."""
    import os

    saved = stored_values()
    for field in FIELDS:
        value = saved.get(field["key"], "")
        if not value:
            continue
        os.environ[field["env"]] = value
        attr = field["setting"]
        if attr:
            setattr(settings, attr, value)
    cloud = getattr(settings, "CLOUDINARY", None)
    if isinstance(cloud, dict):
        name = saved.get("cloudinaryCloudName", "")
        api_key = saved.get("cloudinaryApiKey", "")
        secret = saved.get("cloudinaryApiSecret", "")
        if name:
            cloud["CLOUD_NAME"] = name
        if api_key:
            cloud["API_KEY"] = api_key
        if secret:
            cloud["API_SECRET"] = secret


def status_for(key: str, saved: dict[str, str]) -> str:
    if saved.get(key):
        return "console"
    import os

    if os.environ.get(_BY_KEY[key]["env"], "").strip():
        return "server"
    return "empty"


def public_payload() -> dict[str, str]:
    apply_overlay()
    return {field["key"]: effective(field["key"]) for field in FIELDS if field["public"]}


def staff_payload() -> dict:
    apply_overlay()
    saved = stored_values()
    groups: list[str] = []
    fields = []
    for field in FIELDS:
        if field["group"] not in groups:
            groups.append(field["group"])
        value = effective(field["key"]) if not field["secret"] else ""
        fields.append({
            "key": field["key"],
            "label": field["label"],
            "hint": field["hint"],
            "group": field["group"],
            "secret": field["secret"],
            "value": value,
            "status": status_for(field["key"], saved),
        })
    return {"groups": groups, "fields": fields}


def save_values(incoming: dict, clear: list[str] | None = None) -> dict[str, str]:
    from homepage.models import IntegrationSettings

    row, _ = IntegrationSettings.objects.get_or_create(pk=1, defaults={"values": {}})
    current = dict(row.values) if isinstance(row.values, dict) else {}
    for key in clear or []:
        if key in _BY_KEY:
            current.pop(key, None)
    for key, raw in incoming.items():
        if key not in _BY_KEY or not isinstance(raw, str):
            continue
        value = raw.strip()
        if _BY_KEY[key]["secret"] and not value:
            continue
        if value:
            current[key] = value[:4000]
        else:
            current.pop(key, None)
    row.values = current
    row.save(update_fields=["values", "updated_at"])
    invalidate()
    apply_overlay()
    return {key: value for key, value in current.items() if key in _BY_KEY}
