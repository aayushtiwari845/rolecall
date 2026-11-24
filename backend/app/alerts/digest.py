"""Daily email digest: new matches from the personal feed plus each saved alert."""

from __future__ import annotations

import html
import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Alert, Interaction, Preferences, User
from app.search.engine import recommend, search
from app.search.filters import JobFilters
from app.search.personalize import build_context, filters_from_prefs
from app.search.rank import Ranked

log = logging.getLogger(__name__)
IST = timedelta(hours=5, minutes=30)


def mail_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def send_email(to: str, subject: str, html_body: str, text_body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


def _fresh(items: list[Ranked], since: datetime) -> list[Ranked]:
    return [r for r in items if r.job.first_seen_at and r.job.first_seen_at >= since]


def build_digest(session: Session, user: User, since: datetime) -> list[tuple[str, list[Ranked]]]:
    ctx = build_context(session, user)
    sections: list[tuple[str, list[Ranked]]] = []
    top = _fresh(
        recommend(session, ctx, filters_from_prefs(user.preferences, ctx), limit=60), since
    )[:10]
    if top:
        sections.append(("New matches for you", top))
    for alert in session.scalars(
        select(Alert).where(Alert.user_id == user.id, Alert.enabled.is_(True))
    ):
        items = _fresh(
            search(
                session,
                alert.query,
                JobFilters(**(alert.filters or {})),
                user=ctx,
                limit=40,
                use_rerank=False,
            ),
            since,
        )[:6]
        if items:
            sections.append((f"Alert: {alert.name}", items))
            alert.last_sent_at = datetime.now(UTC)
    return sections


def render(user: User, sections: list[tuple[str, list[Ranked]]]) -> tuple[str, str, str]:
    web = get_settings().web_url.rstrip("/")
    total = sum(len(s[1]) for s in sections)
    subject = f"{total} new role{'s' if total != 1 else ''} for you on Rolecall"
    parts, text = [], []
    for title, items in sections:
        parts.append(
            f'<h2 style="font:600 16px system-ui;margin:24px 0 8px">{html.escape(title)}</h2>'
        )
        text.append(f"\n{title}\n" + "-" * len(title))
        for r in items:
            j = r.job
            why = html.escape(" · ".join(r.reasons[:2]))
            parts.append(
                f'<div style="padding:12px 0;border-bottom:1px solid #eee;font:14px system-ui">'
                f'<a href="{web}/jobs/{j.id}" style="color:#111;font-weight:600;text-decoration:none">{html.escape(j.title)}</a>'
                f'<div style="color:#555">{html.escape(j.company_name)} · {html.escape(j.location_raw or "")} · {r.match}% match</div>'
                f'<div style="color:#777;font-size:12px">{why}</div></div>'
            )
            text.append(f"* {j.title} at {j.company_name} ({r.match}% match): {web}/jobs/{j.id}")
    body = (
        f'<div style="max-width:560px;margin:auto"><p style="font:14px system-ui">Hi {html.escape(user.name or "there")},</p>'
        + "".join(parts)
        + f'<p style="font:12px system-ui;color:#888;margin-top:24px">Change or stop these emails in '
        f'<a href="{web}/settings">settings</a>.</p></div>'
    )
    return subject, body, "\n".join(text) + f"\n\nManage emails: {web}/settings"


def run_digests(session: Session, force_user_id=None) -> int:
    """Send digests to users whose chosen IST hour is now (or one user when forced)."""
    if not mail_configured():
        log.info("SMTP not configured; skipping digests")
        return 0
    now = datetime.now(UTC)
    hour_ist = (now + IST).hour
    q = select(User).join(Preferences).where(Preferences.digest_enabled.is_(True))
    if force_user_id:
        q = select(User).where(User.id == force_user_id)
    else:
        q = q.where(Preferences.digest_hour_ist == hour_ist)
    sent = 0
    for user in session.scalars(q):
        prefs = user.preferences
        last = prefs.last_digest_at if prefs else None
        if not force_user_id and last and now - last < timedelta(hours=20):
            continue
        since = last or now - timedelta(days=1)
        sections = build_digest(session, user, since)
        if prefs:
            prefs.last_digest_at = now
        if sections:
            subject, body, text = render(user, sections)
            try:
                send_email(user.email, subject, body, text)
                sent += 1
                for _, items in sections:
                    session.add_all(
                        [
                            Interaction(
                                user_id=user.id,
                                job_id=r.job.id,
                                type="impression",
                                surface="digest",
                            )
                            for r in items
                        ]
                    )
            except (smtplib.SMTPException, OSError):
                log.exception("digest to %s failed", user.id)
        session.commit()
    return sent
