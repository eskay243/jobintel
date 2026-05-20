from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from jobintel import config
from jobintel.models import Job

log = logging.getLogger(__name__)


def _html_digest(jobs: list[Job], subject_hint: str) -> str:
    lines = [
        "<html><body style='font-family:system-ui,sans-serif;max-width:720px'>",
        f"<h2>{escape(subject_hint)}</h2>",
        f"<p>{len(jobs)} new role(s) matching your filters.</p>",
        "<ul style='padding-left:1.2em'>",
    ]
    for j in jobs:
        regions = ", ".join(j.regions) if j.regions else "—"
        lines.append("<li style='margin-bottom:1em'>")
        lines.append(f"<strong><a href=\"{escape(j.url)}\">{escape(j.title)}</a></strong><br>")
        lines.append(f"{escape(j.company)} · {escape(regions)} · {escape(j.source)}<br>")
        if j.location_text:
            lines.append(f"<small>{escape(j.location_text[:200])}</small>")
        lines.append("</li>")
    lines.append("</ul><p style='color:#666;font-size:12px'>Sent by JobIntel</p></body></html>")
    return "\n".join(lines)


def send_digest(jobs: list[Job], subject: str | None = None) -> None:
    if not jobs:
        return
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        raise RuntimeError("Set SMTP_USER and SMTP_PASSWORD in .env to send email.")
    subj = subject or f"JobIntel: {len(jobs)} new roles (AI / SaaS / fintech / health)"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subj
    msg["From"] = config.MAIL_FROM
    msg["To"] = config.MAIL_TO
    plain = "\n".join(f"- {j.title} @ {j.company}\n  {j.url}\n" for j in jobs)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(_html_digest(jobs, subj), "html", "utf-8"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.sendmail(config.MAIL_FROM, [config.MAIL_TO], msg.as_string())
        log.info("Email sent: %d jobs → %s", len(jobs), config.MAIL_TO)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("SMTP send failed: %s", exc)
        raise
