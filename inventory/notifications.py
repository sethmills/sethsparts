"""Email notifications, sent over SMTP.

Opt-in twice over: the owner must configure an SMTP server, and turn each notification
on individually. Nothing is sent until both happen. The app sends as the owner's own
account (a Gmail app password is the documented path) to the address they choose — so
"you got a message / connection / search while you were away" lands in their normal
inbox.

Sending is synchronous and best-effort: a notification that fails must not fail the
thing that triggered it. It is wrapped so a bad password or an unreachable server
degrades to "no email", never to "the peer's request broke". The SMTP timeout is short
so a misconfigured server adds at most a couple of seconds to the inbound request that
triggered the notification, not enough to make the peer's own 15-second timeout trip.
"""
from __future__ import annotations

import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr

from .site_config import get_site_settings, site_name

SMTP_TIMEOUT = 5


def is_configured() -> bool:
    s = get_site_settings()
    return bool(s and s.email_enabled and s.smtp_host and s.smtp_user and s.smtp_password)


def send(subject, body, to=None) -> tuple[bool, str]:
    """Send one plain-text email. Returns `(sent, error)` so the settings page's test
    button can show what went wrong; the notification path ignores the result.

    `to` overrides the recipient — the notification path always uses notify_email, but
    a caller like the feedback form passes the maintainer's address explicitly."""
    s = get_site_settings()
    if not (s and s.email_enabled and s.smtp_host and s.smtp_user and s.smtp_password):
        return False, "Email is not configured yet."

    to = (to or s.notify_email or s.email_from or s.smtp_user).strip()
    from_ = (s.email_from or s.smtp_user).strip()

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = formataddr((site_name(), from_))
    message["To"] = to

    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT) as server:
            server.ehlo()
            if s.smtp_use_tls:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(s.smtp_user, s.smtp_password)
            server.sendmail(from_, [to], message.as_string())
    except Exception as exc:
        # smtplib raises several types (SMTPAuthenticationError, SMTPConnectError,
        # socket errors...); any of them means "no mail went out", so catch the lot.
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _maybe(flag_field, subject, body):
    """Send only when that notification is turned on. Failures are swallowed on purpose
    — a notification must never break the request that triggered it."""
    s = get_site_settings()
    if not (s and getattr(s, flag_field, False)):
        return
    send(subject, body)


def on_message_received(peer):
    _maybe(
        "notify_on_message",
        f"[{site_name()}] New message from {peer.name}",
        f"{peer.name} sent you a message. Open {site_name()} to read it and reply.",
    )


def on_connection(peer):
    _maybe(
        "notify_on_connection",
        f"[{site_name()}] {peer.name} connected",
        f"{peer.name} has connected to your workshop.",
    )


def on_peer_search(peer, query):
    _maybe(
        "notify_on_search",
        f"[{site_name()}] {peer.name} searched your parts",
        f"{peer.name} searched your shared parts for \"{query}\".",
    )
