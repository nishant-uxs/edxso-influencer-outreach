"""Sending layer with simulation + optional SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from influencer_outreach.config import Settings
from influencer_outreach.models import InfluencerProfile, OutreachMessages, OutreachLogEntry, SendStatus
from influencer_outreach.tracking.store import OutreachStore
from influencer_outreach.utils import stable_id

logger = logging.getLogger(__name__)


class OutreachSender:
    def __init__(self, settings: Settings, store: OutreachStore) -> None:
        self.settings = settings
        self.store = store

    def send_email(
        self,
        profile: InfluencerProfile,
        messages: OutreachMessages,
        *,
        simulate: bool = True,
    ) -> OutreachLogEntry:
        dedupe = stable_id("email", profile.id, messages.email_subject)

        if not profile.has_email:
            entry = OutreachLogEntry(
                influencer_id=profile.id,
                name=profile.name,
                email="Not Found",
                message_generated=True,
                sent=False,
                status=SendStatus.SKIPPED,
                detail="No valid contact email",
                dedupe_key=dedupe,
            )
            self.store.record(entry)
            return entry

        if self.store.already_sent(dedupe):
            entry = OutreachLogEntry(
                influencer_id=profile.id,
                name=profile.name,
                email=profile.contact_email,
                message_generated=True,
                sent=False,
                status=SendStatus.SKIPPED,
                detail="Duplicate outreach prevented",
                dedupe_key=dedupe,
            )
            self.store.record(entry)
            return entry

        if simulate or not self._smtp_configured():
            entry = OutreachLogEntry(
                influencer_id=profile.id,
                name=profile.name,
                email=profile.contact_email,
                message_generated=True,
                sent=True,
                status=SendStatus.SIMULATED,
                detail="Simulated send (SMTP not configured or --simulate)",
                dedupe_key=dedupe,
            )
            self.store.record(entry)
            logger.info("SIMULATED email -> %s (%s)", profile.contact_email, profile.name)
            return entry

        try:
            self._smtp_send(profile.contact_email, messages.email_subject, messages.email_body)
            entry = OutreachLogEntry(
                influencer_id=profile.id,
                name=profile.name,
                email=profile.contact_email,
                message_generated=True,
                sent=True,
                status=SendStatus.SENT,
                detail="SMTP accepted message",
                dedupe_key=dedupe,
            )
            self.store.record(entry)
            return entry
        except Exception as exc:  # noqa: BLE001
            entry = OutreachLogEntry(
                influencer_id=profile.id,
                name=profile.name,
                email=profile.contact_email,
                message_generated=True,
                sent=False,
                status=SendStatus.FAILED,
                detail=str(exc),
                dedupe_key=dedupe,
            )
            self.store.record(entry)
            return entry

    def _smtp_configured(self) -> bool:
        return bool(self.settings.smtp_user and self.settings.smtp_password and self.settings.smtp_from)

    def _smtp_send(self, to_email: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.settings.smtp_from
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            smtp.send_message(msg)
