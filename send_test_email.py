"""
send_test_email.py
------------------
Sends the rendered test_handoff_from_db.html via Resend.
Reads the already-rendered file — run test_db_to_email.py first.

Usage:
    python send_test_email.py
"""

import os, sys, requests, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
if not RESEND_API_KEY:
    print("ERROR: RESEND_API_KEY not found in .env")
    sys.exit(1)

HTML_FILE = Path(__file__).parent.parent / "test_handoff_from_db.html"
if not HTML_FILE.exists():
    print(f"ERROR: {HTML_FILE} not found — run test_db_to_email.py first")
    sys.exit(1)

html = HTML_FILE.read_text(encoding="utf-8")

payload = {
    "from":    "Peregrine <onboarding@resend.dev>",
    "to":      ["arrowroot56@gmail.com"],
    "subject": "Cruise Profile: Test Send — Alaska | Couple",
    "html":    html,
}

print("Sending via Resend...")
r = requests.post(
    "https://api.resend.com/emails",
    headers={
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type":  "application/json",
    },
    json=payload,
)

if r.ok:
    data = r.json()
    print(f"Sent. Email ID: {data.get('id')}")
    print("Check arrowroot56@gmail.com")
else:
    print(f"Failed: {r.status_code}")
    print(r.text)
