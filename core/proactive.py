"""
Proactive checks — email watcher, calendar meeting alerts.

These are one-shot functions registered with `core.scheduler` as interval jobs.
Delivery goes through `core.router`, which picks the right channel based on
presence (HUD/TTS at the desk, FCM push when away, silent during quiet hours).

State (de-dupe sets) survives restarts via data/proactive_state.txt so we
don't re-fire alerts for emails we already saw.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from core import router


# Per-sender triage cache so we don't re-run the LLM for known noise senders
_SENDER_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "email_sender_cache.json"
_sender_cache: dict[str, dict] = {}


_seen_email_ids: set[str] = set()
_notified_event_ids: set[str] = set()
_state_path = Path(__file__).resolve().parent.parent / "data" / "proactive_state.txt"
_email_bootstrap_done = False


def _load_state() -> None:
    if not _state_path.is_file():
        return
    try:
        for line in _state_path.read_text().splitlines():
            if line.startswith("E:"):
                _seen_email_ids.add(line[2:])
            elif line.startswith("C:"):
                _notified_event_ids.add(line[2:])
    except Exception as exc:
        logger.warning(f"proactive: failed to load state: {exc}")


def _save_state() -> None:
    try:
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        emails = list(_seen_email_ids)[-500:]
        events = list(_notified_event_ids)[-500:]
        lines = [f"E:{e}" for e in emails] + [f"C:{c}" for c in events]
        _state_path.write_text("\n".join(lines))
    except Exception as exc:
        logger.warning(f"proactive: failed to save state: {exc}")


# ─────────────────────────────────────────────────────────────────
# Email check (one shot — call from scheduler interval job)
# ─────────────────────────────────────────────────────────────────

def check_emails_once() -> None:
    """Look at unread inbox, fire router notifications for new ones."""
    global _email_bootstrap_done
    try:
        from tools.gmail import _get_gmail_service, _parse_message
        service = _get_gmail_service()
        result = service.users().messages().list(
            userId="me", q="is:unread", maxResults=10
        ).execute()
        messages = result.get("messages", []) or []

        new_ids: list[str] = []
        for m in messages:
            if m["id"] in _seen_email_ids:
                continue
            if not _email_bootstrap_done:
                # First run: prime the seen-set so we don't spam old unread mail
                _seen_email_ids.add(m["id"])
                continue
            new_ids.append(m["id"])

        for mid in new_ids:
            try:
                full = service.users().messages().get(
                    userId="me", id=mid, format="full"
                ).execute()
                parsed = _parse_message(full)

                # ── Triage: classify before notifying ───────────
                triage = _triage_email(parsed)
                category = triage["category"]
                logger.info(
                    f"email triage: {parsed['from'][:40]} → {category} "
                    f"({'cached' if triage.get('from_cache') else 'llm'})"
                )

                if category == "noise":
                    # Drop silently — user doesn't want this on their phone
                    pass
                else:
                    sender = parsed["from"].split("<")[0].strip(" \"'")
                    icon = {"urgent": "🚨", "important": "📧",
                            "informational": "📬"}.get(category, "📧")
                    title = f"{icon} {sender or 'New email'}"[:80]
                    body = (parsed["subject"] or parsed["snippet"])[:200]

                    urgency = ("high" if category == "urgent"
                               else "normal" if category == "important"
                               else "low")

                    router.notify(
                        title=title, body=body,
                        urgency=urgency,
                        kind="email",
                        data={
                            "message_id": mid,
                            "triage_category": category,
                            "triage_reason": triage.get("reason", ""),
                        },
                    )
            except Exception as exc:
                logger.warning(f"proactive email parse failed: {exc}")
            _seen_email_ids.add(mid)

        if not _email_bootstrap_done:
            logger.info(
                f"proactive: bootstrapped with {len(_seen_email_ids)} known emails"
            )
            _email_bootstrap_done = True
        elif new_ids:
            _save_state()

    except Exception as exc:
        logger.debug(f"proactive email check: {exc}")


# ─────────────────────────────────────────────────────────────────
# Calendar meeting alert (one shot)
# ─────────────────────────────────────────────────────────────────

def check_meetings_once(lead_minutes: int = 10) -> None:
    """Notify ~lead_minutes before each upcoming event (once per event)."""
    try:
        from tools.calendar_tool import _get_calendar_service
        service = _get_calendar_service()
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=lead_minutes + 5)

        events_result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=window_end.isoformat(),
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        for ev in events_result.get("items", []) or []:
            ev_id = ev.get("id", "")
            if not ev_id or ev_id in _notified_event_ids:
                continue
            start = ev.get("start", {})
            if "dateTime" not in start:
                continue  # skip all-day
            dt_start = datetime.fromisoformat(start["dateTime"])
            if dt_start.tzinfo is None:
                dt_start = dt_start.replace(tzinfo=timezone.utc)
            minutes_until = (dt_start - now).total_seconds() / 60
            if minutes_until > lead_minutes or minutes_until < -1:
                continue

            title_text = ev.get("summary", "(untitled)")
            location = ev.get("location", "")
            local_time = dt_start.astimezone().strftime("%H:%M")
            mins = max(0, round(minutes_until))

            title = f"🗓 In {mins} min: {title_text}"[:80]
            body = local_time + (f" · {location}" if location else "")

            # Meeting alerts are HIGH urgency: speak it AND push to phone.
            router.notify(
                title=title, body=body,
                urgency="high",
                kind="calendar",
                data={"event_id": ev_id, "minutes_until": str(mins)},
            )
            _notified_event_ids.add(ev_id)
            _save_state()

    except Exception as exc:
        logger.debug(f"proactive calendar check: {exc}")


# ─────────────────────────────────────────────────────────────────
# Bootstrap state at import time
# ─────────────────────────────────────────────────────────────────

_load_state()


# ─────────────────────────────────────────────────────────────────
# Email triage (LLM classifier with sender cache)
# ─────────────────────────────────────────────────────────────────

_TRIAGE_CATEGORIES = ("urgent", "important", "informational", "noise")


def _load_sender_cache() -> None:
    global _sender_cache
    if not _SENDER_CACHE_PATH.is_file():
        return
    try:
        _sender_cache = json.loads(_SENDER_CACHE_PATH.read_text())
    except Exception:
        _sender_cache = {}


def _save_sender_cache() -> None:
    try:
        _SENDER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        trimmed = dict(list(_sender_cache.items())[-200:])
        _SENDER_CACHE_PATH.write_text(json.dumps(trimmed))
    except Exception as exc:
        logger.warning(f"email triage save cache failed: {exc}")


_load_sender_cache()


def _triage_email(parsed: dict) -> dict:
    """Classify an email into urgent / important / informational / noise.

    Uses a per-sender cache: if the same sender has been seen ≥2 times with
    the same low-priority verdict, we skip the LLM and reuse it. Urgent and
    important verdicts are NEVER cached (must re-evaluate each time).
    """
    sender = (parsed.get("from") or "").strip().lower()
    sender_email = sender.split("<")[-1].rstrip(">").strip() if "<" in sender else sender
    cache_entry = _sender_cache.get(sender_email)

    if cache_entry and cache_entry.get("hits", 0) >= 2 and \
            cache_entry["category"] in ("noise", "informational"):
        return {**cache_entry, "from_cache": True}

    try:
        from core.config import load_config
        from openai import OpenAI

        cfg = load_config()
        oai = cfg.get("apis", {}).get("openai", {})
        client = OpenAI(api_key=oai.get("api_key", ""))

        subject = parsed.get("subject") or ""
        snippet = (parsed.get("snippet") or "")[:600]

        sys_prompt = (
            "You triage incoming personal email for sir Purna Sai. Reply ONLY with "
            'valid JSON of shape {"category":"urgent|important|informational|noise","reason":"<≤80 chars>"}.\n'
            "Categories:\n"
            "  urgent        — boss/family/deadline; needs reaction within hours\n"
            "  important     — replies needed, personal correspondence, account security alerts\n"
            "  informational — transactional (receipts, shipping, calendar), ok to skim\n"
            "  noise         — newsletters, marketing, automated digests, spam\n"
            "Default to 'noise' for unknown automated/marketing senders."
        )
        usr_prompt = (f"From: {parsed.get('from','')}\n"
                      f"Subject: {subject}\n"
                      f"Snippet: {snippet}")

        resp = client.chat.completions.create(
            model=oai.get("model", "gpt-4.1-mini"),
            max_tokens=80,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": usr_prompt},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = json.loads(raw) if raw else {}
        cat = str(data.get("category", "noise")).lower()
        if cat not in _TRIAGE_CATEGORIES:
            cat = "noise"
        reason = str(data.get("reason", ""))[:120]

        prev = _sender_cache.get(sender_email, {})
        hits = prev.get("hits", 0) + 1 if prev.get("category") == cat else 1
        _sender_cache[sender_email] = {
            "category": cat, "reason": reason, "hits": hits,
        }
        _save_sender_cache()
        return {"category": cat, "reason": reason, "from_cache": False}

    except Exception as exc:
        logger.warning(f"email triage failed (fallback to important): {exc}")
        return {"category": "important", "reason": str(exc)[:80], "from_cache": False}
