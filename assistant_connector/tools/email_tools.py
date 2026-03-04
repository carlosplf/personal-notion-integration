from __future__ import annotations

import os

from gmail_connector import gmail_connector


def send_email(arguments, context):
    subject = str(arguments.get("subject", "")).strip()
    body = str(arguments.get("body", "")).strip()
    recipient = str(arguments.get("recipient_email", "")).strip()
    reply_to_message_id = str(arguments.get("reply_to_message_id", "")).strip()
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
        reply_to_message_id=reply_to_message_id or None,
    )
    return {
        "status": "sent",
        "subject": final_subject,
        "recipient_email": recipient,
        "tone": tone,
        "signature_applied": bool(signature),
        "provider_result": send_result,
    }


def search_emails(arguments, context):
    query = str(arguments.get("query", "")).strip()
    max_results = _clamp_int(arguments.get("max_results", 10), minimum=1, maximum=50, default=10)
    include_body = bool(arguments.get("include_body", False))
    return gmail_connector.search_emails(
        project_logger=context.project_logger,
        query=query,
        max_results=max_results,
        include_body=include_body,
    )


def read_email(arguments, context):
    message_id = str(arguments.get("message_id", "")).strip()
    if not message_id:
        raise ValueError("message_id is required")
    include_body = bool(arguments.get("include_body", True))
    return gmail_connector.read_email(
        project_logger=context.project_logger,
        message_id=message_id,
        include_body=include_body,
    )


def search_email_attachments(arguments, context):
    query = str(arguments.get("query", "")).strip()
    filename_contains = str(arguments.get("filename_contains", "")).strip()
    max_results = _clamp_int(arguments.get("max_results", 20), minimum=1, maximum=50, default=20)
    return gmail_connector.search_email_attachments(
        project_logger=context.project_logger,
        query=query,
        filename_contains=filename_contains,
        max_results=max_results,
    )


def analyze_email_attachment(arguments, context):
    message_id = str(arguments.get("message_id", "")).strip()
    attachment_id = str(arguments.get("attachment_id", "")).strip()
    filename = str(arguments.get("filename", "")).strip()
    if not message_id:
        raise ValueError("message_id is required")
    if not attachment_id and not filename:
        raise ValueError("attachment_id or filename is required")
    max_chars = _clamp_int(arguments.get("max_chars", 8000), minimum=200, maximum=20000, default=8000)
    return gmail_connector.analyze_email_attachment(
        project_logger=context.project_logger,
        message_id=message_id,
        attachment_id=attachment_id or None,
        filename=filename or None,
        max_chars=max_chars,
    )


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


def _clamp_int(value, *, minimum, maximum, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))
