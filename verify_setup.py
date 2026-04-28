#!/usr/bin/env python3
"""Verify all components are correctly configured before running the voice agent."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent

_passed = 0
_total = 0


def check(name: str, condition: bool, hint: str = "") -> bool:
    global _passed, _total
    _total += 1
    status = "OK  " if condition else "FAIL"
    print(f"  [{status}] {name}")
    if not condition and hint:
        print(f"         -> {hint}")
    if condition:
        _passed += 1
    return condition


# ------------------------------------------------------------------
# Environment variables
# ------------------------------------------------------------------

print("\n=== Environment Variables ===")

openai_key = os.getenv("OPENAI_API_KEY", "")
check("OPENAI_API_KEY set", bool(openai_key), "Set OPENAI_API_KEY in .env")
if openai_key:
    check("OPENAI_API_KEY format (sk-proj-…)", openai_key.startswith("sk-proj-"), "Key should start with 'sk-proj-'")

check("TWILIO_ACCOUNT_SID", bool(os.getenv("TWILIO_ACCOUNT_SID")), "Set TWILIO_ACCOUNT_SID in .env")
check("TWILIO_AUTH_TOKEN",  bool(os.getenv("TWILIO_AUTH_TOKEN")),  "Set TWILIO_AUTH_TOKEN in .env")
check("TWILIO_PHONE_NUMBER", bool(os.getenv("TWILIO_PHONE_NUMBER")), "Set TWILIO_PHONE_NUMBER in .env")
check("SERVER_HOST (ngrok URL)", bool(os.getenv("SERVER_HOST")), "Run ngrok and set SERVER_HOST in .env")

# ------------------------------------------------------------------
# Python packages
# ------------------------------------------------------------------

print("\n=== Python Packages ===")

_PACKAGES = [
    "fastapi",
    "uvicorn",
    "websockets",
    "requests",
    "twilio",
    "dotenv",
    "langgraph",
    "langchain_openai",
    "langchain_google_community",
    "googleapiclient",
    "google",
    "bs4",
]

for pkg in _PACKAGES:
    try:
        __import__(pkg.replace("-", "_"))
        check(pkg, True)
    except ImportError:
        check(pkg, False, f"pip install {pkg}")

# ------------------------------------------------------------------
# Required files
# ------------------------------------------------------------------

print("\n=== Required Files ===")

_FILES = {
    "server.py": "FastAPI entry-point",
    "app/main.py": "FastAPI application",
    "app/api/routes/voice.py": "Voice routes",
    "app/services/openai_realtime.py": "OpenAI Realtime bridge",
    "app/services/scheduler.py": "LangGraph scheduler",
    "app/services/scraper.py": "Website scraper",
    "app/services/twilio_calls.py": "Twilio call initiator",
    "graph_scraper.py": "Scraper + caller LangGraph app",
    ".env": "Environment variables",
    "credentials.json": "Google service-account credentials",
}

for filename, description in _FILES.items():
    check(f"{filename}  ({description})", (ROOT / filename).exists(), f"File not found: {filename}")

# ------------------------------------------------------------------
# Code-level sanity checks
# ------------------------------------------------------------------

print("\n=== Code Checks ===")

try:
    bridge_src = (ROOT / "app" / "services" / "openai_realtime.py").read_text(encoding="utf-8")
    check(
        "openai_realtime.py — audio modalities referenced",
        "openai_modalities" in bridge_src,
        "Audio modalities config missing",
    )
    check(
        "openai_realtime.py — audio delta handler present",
        'response.audio.delta' in bridge_src,
        "Audio delta handler missing",
    )
    check(
        "openai_realtime.py — uses asyncio.get_running_loop()",
        "get_running_loop" in bridge_src,
        "Still using deprecated get_event_loop()",
    )
except OSError:
    check("openai_realtime.py readable", False, "Could not read the file")

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------

print(f"\n{'='*50}")
print(f"Result: {_passed}/{_total} checks passed")
print("=" * 50)

if _passed == _total:
    print("\nAll checks passed. Ready to run.\n")
    print("Next steps:")
    print("  1. ngrok http 8000")
    print("  2. uvicorn server:app --reload --host 0.0.0.0 --port 8000")
    print("  3. Update Twilio webhook → https://<NGROK_URL>/voice/incoming")
    print("  4. python graph_scraper.py")
else:
    issues = _total - _passed
    print(f"\n{issues} issue(s) found — fix them before running.")
    sys.exit(1)
