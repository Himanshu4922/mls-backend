"""Best-effort GoHighLevel sync for leads that are not property inquiries.

Property inquiries already sync through ``inquiry_ghl``. This covers the
remaining forms: newsletter, neighbour alerts, home-valuation requests from a
signed-in visitor, and assignment submissions. Missing CRM keys are a no-op.
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from accounts.services import add_ghl_contact_note, create_ghl_contact

logger = logging.getLogger(__name__)


def push_lead_to_ghl(
    *,
    email: str,
    first_name: str = "",
    last_name: str = "",
    phone: str | None = None,
    source: str,
    tags: list[str] | None = None,
    note: str,
    user=None,
) -> None:
    """Resolve or create a contact and attach a note. Never raises."""
    email = (email or "").strip()
    if not email:
        return
    try:
        contact_id = None
        if user is not None and getattr(user, "ghl_contact_id", None):
            contact_id = user.ghl_contact_id

        if not contact_id:
            User = get_user_model()
            match = (
                User.objects.filter(email__iexact=email)
                .exclude(ghl_contact_id__isnull=True)
                .exclude(ghl_contact_id="")
                .first()
            )
            if match and match.ghl_contact_id:
                contact_id = match.ghl_contact_id

        if not contact_id:
            contact_id = create_ghl_contact(
                first_name or "",
                last_name or "",
                email,
                phone or None,
                source=source,
                tags=tags or [source],
            )
            if contact_id and user is not None and not getattr(user, "ghl_contact_id", None):
                user.ghl_contact_id = contact_id
                user.save(update_fields=["ghl_contact_id"])

        if contact_id and note:
            add_ghl_contact_note(contact_id, note)
    except Exception:
        logger.exception("push_lead_to_ghl failed for source=%s", source)
