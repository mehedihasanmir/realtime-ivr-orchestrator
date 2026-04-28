#!/usr/bin/env python3
"""
Verification Script - Check all components before running the voice agent
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

print("=" * 60)
print("AI VOICE AGENT - SETUP VERIFICATION")
print("=" * 60)

checks_passed = 0
checks_total = 0


def check(name, condition, error_msg=""):
    global checks_passed, checks_total
    checks_total += 1
    if condition:
        print(f"OK: {name}")
        checks_passed += 1
    else:
        print(f"FAIL: {name}")
        if error_msg:
            print(f"  -> {error_msg}")
    return condition


print("\nCHECKING ENVIRONMENT VARIABLES...")
print("-" * 60)

openai_key = os.getenv("OPENAI_API_KEY")
check("OpenAI API Key", bool(openai_key), "Missing: Set OPENAI_API_KEY in .env")
if openai_key:
    check("  Starts with 'sk-proj-'", openai_key.startswith("sk-proj-"), "Invalid format")

twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
check("Twilio Account SID", bool(twilio_sid), "Missing: Set TWILIO_ACCOUNT_SID in .env")

twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
check("Twilio Auth Token", bool(twilio_token), "Missing: Set TWILIO_AUTH_TOKEN in .env")

twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
check("Twilio Phone Number", bool(twilio_number), "Missing: Set TWILIO_PHONE_NUMBER in .env")

server_host = os.getenv("SERVER_HOST")
check("Server Host (Ngrok URL)", bool(server_host), "Missing: Set SERVER_HOST in .env")

print("\nCHECKING PYTHON PACKAGES...")
print("-" * 60)

packages = [
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

for package in packages:
    try:
        __import__(package.replace("-", "_"))
        check(f"Package: {package}", True)
    except ImportError:
        check(f"Package: {package}", False, f"Install with: pip install {package}")

print("\nCHECKING FILES...")
print("-" * 60)

files = {
    "server.py": "FastAPI entrypoint",
    "app/main.py": "FastAPI app",
    "app/api/routes/voice.py": "Voice routes",
    "app/services/openai_realtime.py": "OpenAI realtime bridge",
    "graph_scraper.py": "Twilio call initiator",
    "tools_scheduler.py": "LangGraph scheduler",
    ".env": "Environment variables",
    "credentials.json": "Google Calendar credentials",
}

root = Path(__file__).resolve().parent

for filename, description in files.items():
    filepath = root / filename
    check(f"{filename} ({description})", filepath.exists(), f"File not found: {filename}")

print("\nCHECKING CONFIGURATIONS...")
print("-" * 60)

try:
    bridge_path = root / "app" / "services" / "openai_realtime.py"
    content = bridge_path.read_text(encoding="utf-8")
    check(
        "OpenAI bridge has audio modalities configured",
        "openai_modalities" in content,
        "Audio modalities configuration missing",
    )
    check(
        "OpenAI bridge has audio.delta handler",
        'response_type == "response.audio.delta"' in content,
        "Audio response handler missing",
    )
except Exception:
    print("FAIL: Could not read OpenAI bridge file")

print("\n" + "=" * 60)
print(f"CHECKS PASSED: {checks_passed}/{checks_total}")
print("=" * 60)

if checks_passed == checks_total:
    print("\nAll checks passed. Setup is ready.")
    print("\nNext steps:")
    print("1. Make sure ngrok is running: ngrok http 8000")
    print("2. Start the server: uvicorn server:app --reload")
    print("3. Update Twilio webhook to: https://<YOUR_NGROK_URL>/voice/incoming")
    print("4. Make a test call: python graph_scraper.py")
else:
    print(f"\n{checks_total - checks_passed} issue(s) found. Fix them before running.")
    sys.exit(1)
#!/usr/bin/env python3
"""
🔍 Verification Script - Check all components before running the voice agent
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

print("=" * 60)
print("🔍 AI VOICE AGENT - SETUP VERIFICATION")
print("=" * 60)

checks_passed = 0
checks_total = 0

def check(name, condition, error_msg=""):
    global checks_passed, checks_total
    checks_total += 1
    if condition:
        print(f"✅ {name}")
        checks_passed += 1
    else:
        print(f"❌ {name}")
        if error_msg:
            print(f"   → {error_msg}")
    return condition

print("\n📋 CHECKING ENVIRONMENT VARIABLES...")
print("-" * 60)

openai_key = os.getenv("OPENAI_API_KEY")
check("OpenAI API Key", bool(openai_key), "Missing: Set OPENAI_API_KEY in .env")
if openai_key:
    check("  → Starts with 'sk-proj-'", openai_key.startswith("sk-proj-"), "Invalid format")

twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
check("Twilio Account SID", bool(twilio_sid), "Missing: Set TWILIO_ACCOUNT_SID in .env")

twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
check("Twilio Auth Token", bool(twilio_token), "Missing: Set TWILIO_AUTH_TOKEN in .env")

twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
check("Twilio Phone Number", bool(twilio_number), "Missing: Set TWILIO_PHONE_NUMBER in .env")

server_host = os.getenv("SERVER_HOST")
check("Server Host (Ngrok URL)", bool(server_host), "Missing: Set SERVER_HOST in .env (copy from ngrok)")

print("\n📦 CHECKING PYTHON PACKAGES...")
print("-" * 60)

packages = [
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

for package in packages:
    try:
        __import__(package.replace("-", "_"))
        check(f"Package: {package}", True)
    except ImportError:
        check(f"Package: {package}", False, f"Install with: pip install {package}")

print("\n📁 CHECKING FILES...")
print("-" * 60)

files = {
    "server.py": "FastAPI entrypoint",
    "app/main.py": "FastAPI app",
    "app/api/routes/voice.py": "Voice routes",
    "app/services/openai_realtime.py": "OpenAI realtime bridge",
    "graph_scraper.py": "Twilio call initiator",
    "tools_scheduler.py": "LangGraph scheduler",
    ".env": "Environment variables",
    "credentials.json": "Google Calendar credentials",
}

root = Path(__file__).resolve().parent

for filename, description in files.items():
    filepath = root / filename
    check(f"{filename} ({description})", filepath.exists(), f"File not found: {filename}")

print("\n🌐 CHECKING CONFIGURATIONS...")
print("-" * 60)

# Check if OpenAI bridge includes audio and delta handling
try:
    bridge_path = root / "app" / "services" / "openai_realtime.py"
    content = bridge_path.read_text(encoding="utf-8")
    check(
        "OpenAI bridge has audio modalities configured",
        "openai_modalities" in content,
        "Audio modalities configuration missing",
    )
    check(
        "OpenAI bridge has audio.delta handler",
        'response_type == "response.audio.delta"' in content,
        "Audio response handler missing",
    )
except Exception:
    print("❌ Could not read OpenAI bridge file")

print("\n" + "=" * 60)
print(f"✅ CHECKS PASSED: {checks_passed}/{checks_total}")
print("=" * 60)

if checks_passed == checks_total:
    print("\n🎉 All checks passed! Your setup is ready.")
    print("\nNext steps:")
    print("1. Make sure ngrok is running: ngrok http 8000")
    print("2. Start the server: uvicorn server:app --reload")
    print("3. Update Twilio webhook to: https://<YOUR_NGROK_URL>/voice/incoming")
    print("4. Make a test call: python graph_scraper.py")
else:
    print(f"\n⚠️  {checks_total - checks_passed} issue(s) found. Please fix them before running.")
    sys.exit(1)
