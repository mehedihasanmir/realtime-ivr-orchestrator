from __future__ import annotations

import logging
import os

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = float(os.getenv("SCRAPER_TIMEOUT", "10"))
_DEFAULT_MAX_CHARS = int(os.getenv("SCRAPER_MAX_CHARS", "800"))
_USER_AGENT = "VoiceAgent/1.0"


def scrape_website(
    url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Fetch a URL and return its paragraph text, truncated to *max_chars*."""
    logger.info("Scraping %s", url)
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        paragraphs = (p.get_text(separator=" ", strip=True) for p in soup.find_all("p"))
        text = " ".join(filter(None, paragraphs))
        text = " ".join(text.split())  # collapse whitespace

        if not text:
            logger.warning("No paragraph text found at %s", url)
            return "No website data available."

        return text[:max_chars]
    except Exception as exc:
        logger.exception("Scraping failed for %s: %s", url, exc)
        return "No website data available."
