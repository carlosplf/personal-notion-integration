from __future__ import annotations

import os

from gmail_connector import gmail_connector


def send_email(arguments, context):
    subject = str(arguments.get("subject", "")).strip()
    body = str(arguments.get("body", "")).strip()
    recipient = str(arguments.get("recipient_email", "")).strip()
    if not recipient:
        raise ValueError("recipient_email is required")
    if not subject:
        raise ValueError("subject is required")
    if not body:
        raise ValueError("body is required")

    include_signature = bool(arguments.get("include_signature", True))
    tone = str(arguments.get("tone_override", "")).strip() or _get_email_tone()
    signature = _get_email_signature() if include_signature else ""

    final_subject = _apply_subject_prefix(subject)
    final_body = _compose_email_body(body, signature=signature)

    send_result = gmail_connector.send_custom_email(
        project_logger=context.project_logger,
        subject=final_subject,
        body_text=final_body,
        email_to=recipient,
        body_subtype="plain",
    )
    return {
        "status": "sent",
        "subject": final_subject,
        "recipient_email": recipient,
        "tone": tone,
        "signature_applied": bool(signature),
        "provider_result": send_result,
    }


def _apply_subject_prefix(subject):
    prefix = str(os.getenv("EMAIL_ASSISTANT_SUBJECT_PREFIX", "")).strip()
    if not prefix:
        return subject
    return f"{prefix} {subject}".strip()


def _compose_email_body(body, *, signature):
    sections = [body]
    if signature:
        sections.append(f"\n\n{signature}")
    return "".join(sections).strip()


def _get_email_tone():
    return str(
        os.getenv("EMAIL_ASSISTANT_TONE", "claro, cordial e objetivo")
    ).strip() or "claro, cordial e objetivo"


def _get_email_signature():
    return str(os.getenv("EMAIL_ASSISTANT_SIGNATURE", "")).strip()
