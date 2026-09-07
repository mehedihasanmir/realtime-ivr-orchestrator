"""Place an outbound AI call primed with scraped website context.

Usage:
    python scripts/outbound_call.py
    python scripts/outbound_call.py --url https://example.com --phone +8801XXXXXXXXX

Defaults come from TARGET_URL and TARGET_PHONE in .env.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from app.services.scraper import scrape_website
from app.services.twilio_calls import initiate_call


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("TARGET_URL", "https://www.wikipedia.org/"))
    parser.add_argument("--phone", default=os.getenv("TARGET_PHONE"))
    args = parser.parse_args()

    if not args.phone:
        parser.error("No phone number: pass --phone or set TARGET_PHONE in .env")

    content = scrape_website(args.url)
    call_sid = initiate_call(args.phone, content)
    print(f"Call initiated — SID: {call_sid}")


if __name__ == "__main__":
    main()
