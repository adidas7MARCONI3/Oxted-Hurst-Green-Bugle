"""Twilio SMS alerts for train disruptions and bin reminders.

Required env vars:
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_FROM   — your Twilio number, e.g. +441234567890
  TWILIO_TO     — recipient number, e.g. +447700123456
"""
import os
import httpx
import base64


class SMSAlert:
    API = "https://api.twilio.com/2010-04-01"

    def __init__(self):
        self.sid = os.environ["TWILIO_ACCOUNT_SID"]
        self.token = os.environ["TWILIO_AUTH_TOKEN"]
        self.from_number = os.environ["TWILIO_FROM"]
        self.to_number = os.environ["TWILIO_TO"]

    def send(self, body: str) -> dict:
        auth = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        resp = httpx.post(
            f"{self.API}/Accounts/{self.sid}/Messages.json",
            headers={"Authorization": f"Basic {auth}"},
            data={
                "From": self.from_number,
                "To": self.to_number,
                "Body": body[:1600],
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def train_alert(self, disruptions: list[dict]) -> None:
        if not disruptions:
            return
        lines = ["🚂 Oxted Line alert:"]
        for d in disruptions[:5]:
            lines.append(f"• {d.get('title', d.get('description', ''))[:100]}")
        self.send("\n".join(lines))

    def bin_reminder(self, collections: list[dict]) -> None:
        if not collections:
            return
        lines = ["🗑️ Bin reminder for tomorrow:"]
        for c in collections:
            lines.append(f"• {c.get('title', '')}")
        self.send("\n".join(lines))
