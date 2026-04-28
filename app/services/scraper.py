import logging
import os

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = float(os.getenv("SCRAPER_TIMEOUT", "10"))
DEFAULT_MAX_CHARS = int(os.getenv("SCRAPER_MAX_CHARS", "800"))


def scrape_website(url: str, *, timeout: float = DEFAULT_TIMEOUT, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    logger.info("Scraping %s", url)
    try:
        headers = {"User-Agent": "VoiceAgent/1.0"}
        response = requests.get(url, timeout=timeout, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        text_content = " ".join(p.get_text() for p in soup.find_all("p"))
        text_content = " ".join(text_content.split())

        if not text_content:
            return "No website data available."
        return text_content[:max_chars]
    except Exception as exc:
        logger.exception("Scraping failed: %s", exc)
        return "No website data available."
