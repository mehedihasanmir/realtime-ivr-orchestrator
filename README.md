# AI Voice Agent

A phone-first assistant that calls users, streams audio in real time, and can book meetings on the caller's own Google Calendar. The goal is to make a simple voice flow feel useful: scrape a URL for context, talk to the user, and schedule a meeting without leaving the call.

This project exists to demonstrate a practical, end-to-end voice agent that combines telephony, real-time AI, and calendar automation in one deployable service.

## Badges

![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-web%20api-009688.svg)

## Table of Contents

- [Demo / Screenshot](#demo--screenshot)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Contributing](#contributing)
- [License](#license)

## Demo / Screenshot

No public demo link yet. To see the full flow locally, follow the Usage section and place a call with `python graph_scraper.py`.

## Features

- Real-time phone calls with Twilio Media Streams and OpenAI Realtime
- Website scraping to prime the assistant with live context
- Google Calendar OAuth per user (each caller schedules on their own calendar)
- Simple LangGraph workflow for scraping + calling
- E.164 phone normalization to keep user identity consistent

## Installation

### Prerequisites

- Python 3.11+
- A Twilio account with a phone number
- A Google Cloud project with OAuth client configured
- OpenAI API key
- ngrok (or any public tunnel)

### Setup

```bash
# 1) Create and activate a virtual environment (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) Install dependencies
pip install -r requirements.txt

# 3) Create your .env file (see Configuration below)

# 4) Download OAuth client_secret.json from Google Cloud Console
#    and place it at the project root (or set GOOGLE_OAUTH_CLIENT_SECRETS)
```

## Usage

### 1) Start the API server

```bash
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### 2) Start ngrok

```bash
ngrok http 8000
```

Copy the ngrok domain into your `.env` as `SERVER_HOST` (no scheme).

### 3) Configure Twilio webhook

Set your Twilio number's Voice webhook to:

```
https://<YOUR_NGROK_DOMAIN>/voice/incoming
```

### 4) Connect a user to Google Calendar

Open this URL in a browser and click Allow:

```
https://<YOUR_NGROK_DOMAIN>/auth/google/start?user_id=%2B15551234567
```

- `user_id` should be the caller's phone number in E.164.
- After consent, tokens are saved to `oauth_tokens.json`.

### 5) Place a call via the scraper workflow

```bash
python graph_scraper.py
```

This script uses `TARGET_URL` and `TARGET_PHONE` from `.env`, scrapes the page, then initiates a Twilio call.

## Configuration

Create a `.env` file in the project root:

```dotenv
OPENAI_API_KEY=sk-proj-...

TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+15551234567

# Public URL from ngrok (no scheme)
SERVER_HOST=your-tunnel.ngrok-free.dev

# Google OAuth
GOOGLE_OAUTH_CLIENT_SECRETS=client_secret.json
GOOGLE_OAUTH_TOKEN_PATH=oauth_tokens.json
GOOGLE_OAUTH_STATE_SECRET=replace-with-a-random-string

# Scraper defaults (optional)
TARGET_URL=https://www.wikipedia.org/
TARGET_PHONE=+15551234567
SCRAPER_TIMEOUT=10
SCRAPER_MAX_CHARS=800
```

Optional OpenAI settings (defaults are in code):

- `OPENAI_REALTIME_MODEL`
- `OPENAI_REALTIME_URL`
- `OPENAI_VOICE`
- `OPENAI_TEMPERATURE`
- `OPENAI_MAX_TOKENS`
- `OPENAI_MODALITIES`
- `OPENAI_INPUT_AUDIO_FORMAT`
- `OPENAI_OUTPUT_AUDIO_FORMAT`
- `OPENAI_TURN_DETECTION_TYPE`

## API Reference

### `GET /healthz`

Returns a basic health response.

### `GET|POST /voice/incoming`

Twilio webhook endpoint. Accepts standard Twilio Voice webhook parameters. Sends a Media Stream start command and passes context + user_id to the WebSocket.

### `WS /media-stream`

Twilio Media Stream WebSocket. Bridges audio between Twilio and OpenAI Realtime.

### `GET /auth/google/start?user_id=<E.164>`

Starts Google OAuth. `user_id` is the caller identity (E.164 phone is recommended).

### `GET /auth/google/callback`

OAuth callback used by Google to complete consent.

## Contributing

1. Fork the repo and create a feature branch.
2. Install dependencies and run the app locally.
3. Add tests or a reproduction script if your change is non-trivial.
4. Open a PR with a clear description and steps to verify.

## License

License not specified yet.
