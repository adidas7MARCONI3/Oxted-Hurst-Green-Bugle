"""Email alerts via Resend API.

Required env vars:
  RESEND_API_KEY
  ALERT_EMAIL_FROM   — verified sender, e.g. bugle@yourdomain.com
  ALERT_EMAIL_TO     — recipient
"""
import os
import httpx


class EmailAlert:
    API = "https://api.resend.com/emails"

    def __init__(self):
        self.api_key = os.environ["RESEND_API_KEY"]
        self.from_addr = os.environ["ALERT_EMAIL_FROM"]
        self.to_addr = os.environ["ALERT_EMAIL_TO"]

    def send(self, subject: str, html: str, text: str = "") -> dict:
        resp = httpx.post(
            self.API,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={
                "from": self.from_addr,
                "to": [self.to_addr],
                "subject": subject,
                "html": html,
                "text": text or subject,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def train_alert(self, disruptions: list[dict]) -> None:
        if not disruptions:
            return
        items_html = "".join(
            f"<li><strong>{d.get('title', '')}</strong> — {d.get('description', '')[:200]}</li>"
            for d in disruptions[:10]
        )
        html = f"""
        <h2>🚂 Oxted Line Disruption Alert</h2>
        <ul>{items_html}</ul>
        <p><a href="https://www.nationalrail.co.uk/">Check National Rail</a></p>
        """
        self.send("Oxted Line disruption alert", html)

    def bin_reminder(self, collections: list[dict]) -> None:
        if not collections:
            return
        items_html = "".join(f"<li>{c.get('title', '')}</li>" for c in collections)
        html = f"<h2>🗑️ Bin collection tomorrow</h2><ul>{items_html}</ul>"
        self.send("Bin collection reminder", html)

    def daily_digest(self, digest_html: str) -> None:
        self.send("Your Oxted & Hurst Green Bugle", digest_html)
