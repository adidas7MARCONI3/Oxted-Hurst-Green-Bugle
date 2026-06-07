#!/usr/bin/env python3
"""Train disruption checker — runs every 5 minutes 05:00–10:00 on weekdays.

Sends SMS via Twilio and email via Resend when disruptions are detected.
Only alerts once per disruption (tracks sent IDs in a state file).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

STATE_FILE = Path("public/data/output/.train_alert_state.json")


def trigger_redeploy():
    print("GitHub Pages will redeploy automatically on push")
COOLDOWN_MINUTES = 30  # don't re-alert same disruption within this window


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"alerted": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def prune_state(state: dict) -> dict:
    """Remove alerts older than COOLDOWN_MINUTES."""
    now = datetime.now(timezone.utc)
    alerted = {}
    for uid, ts in state.get("alerted", {}).items():
        try:
            age = (now - datetime.fromisoformat(ts)).total_seconds() / 60
            if age < COOLDOWN_MINUTES:
                alerted[uid] = ts
        except Exception:
            pass
    state["alerted"] = alerted
    return state


def main():
    from collectors.trains import TrainsCollector

    result = TrainsCollector().collect()
    disruptions = [
        item for item in result.items
        if item.data.get("cancelled") or item.data.get("disrupted")
    ]

    if not disruptions:
        print("No disruptions detected.")
        return

    state = prune_state(load_state())
    new_disruptions = [d for d in disruptions if d.id not in state["alerted"]]

    if not new_disruptions:
        print(f"{len(disruptions)} disruption(s) known, no new alerts needed.")
        return

    print(f"{len(new_disruptions)} new disruption(s) — sending alerts...")
    disruption_dicts = [{"title": d.title, "description": d.description} for d in new_disruptions]

    sms_sent = False
    email_sent = False

    if os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN"):
        try:
            from alerts.sms import SMSAlert
            SMSAlert().train_alert(disruption_dicts)
            sms_sent = True
            print("  SMS sent.")
        except Exception as exc:
            print(f"  SMS failed: {exc}")

    if os.getenv("RESEND_API_KEY"):
        try:
            from alerts.email import EmailAlert
            EmailAlert().train_alert(disruption_dicts)
            email_sent = True
            print("  Email sent.")
        except Exception as exc:
            print(f"  Email failed: {exc}")

    if sms_sent or email_sent:
        now_ts = datetime.now(timezone.utc).isoformat()
        for d in new_disruptions:
            state["alerted"][d.id] = now_ts
        save_state(state)


if __name__ == "__main__":
    main()
