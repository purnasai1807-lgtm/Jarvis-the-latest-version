"""
Phase 6 — Gmail integration via Google API.

OAuth2 credentials stored in data/google_token.json after first-time browser consent.
Requires data/google_credentials.json (downloaded from Google Cloud Console).

Tools: read_emails, send_email
"""

import base64
import email as email_lib
import json
import os
from pathlib import Path

from loguru import logger

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
_CREDS_FILE = Path("data/google_credentials.json")
_TOKEN_FILE = Path("data/google_token.json")


def _get_gmail_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CREDS_FILE.exists():
                raise FileNotFoundError(
                    f"Google credentials not found at {_CREDS_FILE}. "
                    "Download OAuth credentials from Google Cloud Console and save as data/google_credentials.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_FILE), _SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _decode_body(payload) -> str:
    """Recursively extract plain text from email payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _decode_body(part)
        if result:
            return result
    return ""


def _parse_message(msg: dict) -> dict:
    """Extract subject, sender, snippet, and body from a Gmail message."""
    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    return {
        "id": msg["id"],
        "subject": headers.get("Subject", "(no subject)"),
        "from": headers.get("From", "unknown"),
        "date": headers.get("Date", ""),
        "snippet": msg.get("snippet", ""),
        "body": _decode_body(msg["payload"])[:500],  # first 500 chars
    }


# ── Handlers ─────────────────────────────────────────────────────

def read_emails(max_results: int = 5, query: str = "is:unread", summarize: bool = True) -> str:
    """Fetch recent emails and return a readable summary."""
    try:
        service = _get_gmail_service()
        result = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()

        messages = result.get("messages", [])
        if not messages:
            return f"No emails found for query: '{query}'"

        emails = []
        for m in messages:
            full = service.users().messages().get(
                userId="me", id=m["id"], format="full"
            ).execute()
            emails.append(_parse_message(full))

        lines = [f"Found {len(emails)} email(s) matching '{query}':\n"]
        for i, e in enumerate(emails, 1):
            lines.append(
                f"{i}. From: {e['from']}\n"
                f"   Subject: {e['subject']}\n"
                f"   {e['snippet'][:150]}\n"
            )

        logger.info(f"read_emails: fetched {len(emails)} messages")
        return "\n".join(lines)

    except Exception as exc:
        logger.error(f"read_emails failed: {exc}")
        return f"Could not read emails: {exc}"


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email via Gmail."""
    try:
        from googleapiclient.errors import HttpError
        import email.mime.text

        service = _get_gmail_service()

        msg = email.mime.text.MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        logger.info(f"send_email: sent to {to!r} — subject: {subject!r}")
        return f"Email sent to {to} with subject '{subject}'."

    except Exception as exc:
        logger.error(f"send_email failed: {exc}")
        return f"Could not send email: {exc}"


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "read_emails",
        "description": (
            "Read emails from Gmail. Returns subject, sender, and preview. "
            "Use for: 'any new emails?', 'check my inbox', 'any important emails?', "
            "'morning briefing' (include emails in briefing). "
            "Default fetches 5 unread emails. Use query='is:important is:unread' for important ones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "How many emails to fetch (default 5)",
                },
                "query": {
                    "type": "string",
                    "description": "Gmail search query, e.g. 'is:unread', 'is:important is:unread', 'from:boss@company.com'",
                },
            },
        },
    },
    {
        "name": "send_email",
        "description": (
            "Send an email via Gmail. "
            "Use when the user says 'send an email to X', 'email X saying Y', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]

HANDLERS = {
    "read_emails": read_emails,
    "send_email": send_email,
}
