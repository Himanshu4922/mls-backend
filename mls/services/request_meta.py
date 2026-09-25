"""Who sent a request: client IP and user agent, for lead/activity records.

The site's browser traffic reaches Django through the Next.js server (BFF
routes), so REMOTE_ADDR is that server, not the visitor. The BFF forwards the
visitor's address in X-Forwarded-For; the first entry is the original client.
The value is client-supplied and therefore spoofable: it is fine for lead
context and analytics, never for access control.
"""
from __future__ import annotations

USER_AGENT_MAX_LENGTH = 512


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    candidate = forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR") or ""
    return candidate[:45] or None  # 45 = longest textual IPv6


def user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:USER_AGENT_MAX_LENGTH]
