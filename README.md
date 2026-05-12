# AI Voice Agent

> A production-ready, phone-first AI assistant that calls users, streams audio in real time via OpenAI Realtime API, and books meetings directly on Google Calendar — all within a single voice call.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)
![LangGraph](https://img.shields.io/badge/LangGraph-agentic-orange.svg)
![OpenAI Realtime](https://img.shields.io/badge/OpenAI-Realtime%20API-412991.svg)
![Twilio](https://img.shields.io/badge/Twilio-Media%20Streams-F22F46.svg)
![License](https://img.shields.io/badge/License-TBD-lightgrey.svg)

---

## Table of Contents

<!-- - [Demo](#demo) -->
- [Features](#features)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Contributing](#contributing)
- [License](#license)

---
<!-- 
## Demo

> 📹 **Video demo:** _[]_
> 🌐 **Live link:** _[]_
> 🖼️ **Screenshot:** _[]_

---
 -->

## Features

- **Real-time voice calls** — Bridges Twilio Media Streams with OpenAI Realtime API over WebSocket for sub-second audio streaming
- **Barge-in detection** — Detects user speech mid-response using RMS energy analysis and immediately cancels the AI's output
- **Context-aware conversations** — Scrapes a target URL before the call and injects the content into the assistant's system prompt
- **Google Calendar integration** — Per-user OAuth2 + PKCE flow; the LangGraph scheduler checks for conflicts and books meetings during the call
- **E.164 phone normalization** — Consistent user identity across Twilio caller/callee ambiguity
- **LangGraph orchestration** — Two separate graphs: one for the scrape-then-call pipeline, one for the calendar scheduling agent
- **Typed, validated configuration** — Frozen `Settings` dataclass loaded once via `lru_cache`, fails fast on startup if misconfigured
- **Production-grade defaults** — Silence detection, minimum audio buffer guard, audio format abstraction (G.711 µ-law, A-law, PCM16)

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         graph_scraper.py                           │
│                                                                    │
│   ┌──────────────┐         ┌──────────────┐                        │
│   │  scrape_node │────────▶│  call_node   │                        │
│   │  (scraper.py)│         │(twilio_calls)│                        │
│   └──────────────┘         └──────┬───────┘                        │
└──────────────────────────────────┼────────────────────────────────┘
                                   │ Twilio outbound call
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                       FastAPI Server                             │
│                                                                  │
│  POST /voice/incoming ──────────────────────┐                    │
│  (voice.py)                                 │                    │
│                                             ▼                    │
│                              ┌──────────────────────────┐        │
│  WS /media-stream ──────────▶│     RealtimeBridge        │       │
│  (voice.py)                  │   (openai_realtime.py)    │       │
│                              │                           │       │
│                              │  Twilio WS ◀──▶ OpenAI   │       │
│                              │  Realtime WS              │       │
│                              │                           │       │
│                              │  ┌─────────────────────┐ │       │
│                              │  │  Barge-in Detector  │ │       │
│                              │  │  (RMS energy, VAD)  │ │       │
│                              │  └─────────────────────┘ │       │
│                              │                           │       │
│                              │  schedule_meeting tool ──▶│       │
│                              └──────────────┬────────────┘       │
│                                             │                    │
│                                             ▼                    │
│                              ┌──────────────────────────┐        │
│                              │   SchedulerService        │        │
│                              │   (scheduler.py)          │        │
│                              │                           │        │
│                              │  LangGraph Agent          │        │
│                              │  ┌────────┐ ┌─────────┐  │        │
│                              │  │ agent  │▶│ tools   │  │        │
│                              │  │ node   │◀│ node    │  │        │
│                              │  └────────┘ └─────────┘  │        │
│                              │       │                   │        │
│                              │       ▼                   │        │
│                              │  Google Calendar API      │        │
│                              └───────────────────────────┘        │
│                                                                  │
│  GET  /auth/google/start ──▶ OAuth2 PKCE flow                    │
│  GET  /auth/google/callback ─▶ TokenStore (oauth_tokens.json)    │
│  (auth.py)                                                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## How It Works

### 1. Scrape → Call Pipeline (`graph_scraper.py`)

A two-node LangGraph pipeline kicks off the entire flow:

1. **`scrape_node`** — Fetches the target URL using `requests` + `BeautifulSoup`, extracts paragraph text, and truncates to `SCRAPER_MAX_CHARS` characters.
2. **`call_node`** — Passes the scraped content as a URL-encoded query parameter to Twilio's `calls.create()`, which triggers the `/voice/incoming` webhook.

### 2. Twilio Webhook → WebSocket Handoff (`voice.py`)

When Twilio hits `/voice/incoming`, the server:
- Extracts the caller/callee phone number and resolves a `user_id` (preferring the human side of the call).
- Returns TwiML that opens a **Media Stream** WebSocket back to `/media-stream`, passing `scraped_data` and `user_id` as custom stream parameters.

### 3. Real-Time Audio Bridge (`openai_realtime.py`)

`RealtimeBridge` runs three concurrent async tasks:

| Task | Role |
|---|---|
| `_receive_from_twilio` | Reads G.711 audio frames from Twilio, appends them to OpenAI's input buffer, handles stream start/stop events |
| `_receive_from_openai` | Reads audio deltas and events from OpenAI Realtime, forwards audio to Twilio, handles tool calls |
| `_silence_watcher` | Polls every 500 ms; commits the audio buffer and triggers `response.create` after 1 second of silence |

**Barge-in detection** runs on every incoming audio frame when a response is active. It decodes the G.711 payload, computes RMS energy via `audioop`, and cancels the AI response + clears the Twilio audio buffer if speech is detected above threshold.

**OpenAI VAD** (`input_audio_buffer.speech_started`) also triggers barge-in as a confirmed fallback.

### 4. Meeting Scheduling (`scheduler.py`)

When the user says something like _"book me a meeting next Tuesday at 3pm"_, OpenAI Realtime calls the `schedule_meeting` function tool. The bridge:

1. Deserialises the tool call arguments.
2. Runs `SchedulerService.schedule_meeting()` in a thread pool (`asyncio.to_thread`).
3. Inside the service, a LangGraph `agent → tools` loop uses `langchain-google-community`'s `CalendarToolkit` to check for conflicts and create the event.
4. The result string is sent back as a `function_call_output` conversation item, triggering a new response.

### 5. Google OAuth (`google_oauth.py` + `auth.py`)

Each caller authenticates independently:
- `/auth/google/start?user_id=+1234567890` — generates a PKCE code verifier and HMAC-signed state token, redirects to Google.
- `/auth/google/callback` — verifies the state signature (10-minute TTL), exchanges the code, and persists credentials to `oauth_tokens.json` keyed by E.164 phone number.
- Tokens are refreshed automatically before each scheduling request.

---

## Project Structure

```
ai-voice-agent/
│
├── app/
│   ├── api/
│   │   └── routes/
│   │       ├── auth.py              # Google OAuth start & callback endpoints
│   │       └── voice.py             # Twilio webhook + WebSocket media stream
│   │
│   ├── core/
│   │   ├── config.py                # Typed Settings dataclass, env loading, lru_cache
│   │   └── logging.py               # Logging configuration
│   │
│   ├── services/
│   │   ├── google_oauth.py          # OAuth2 PKCE flow, TokenStore, StateSigner
│   │   ├── openai_realtime.py       # RealtimeBridge — audio bridge + barge-in
│   │   ├── scheduler.py             # LangGraph calendar scheduling agent
│   │   ├── scraper.py               # BeautifulSoup URL scraper
│   │   └── twilio_calls.py          # Outbound call initiator
│   │
│   └── main.py                      # FastAPI app factory, router registration
│
├── graph_scraper.py                 # Entry point: LangGraph scrape → call pipeline
├── server.py                        # Uvicorn entry point (imports app from main.py)
├── tools_scheduler.py               # Exposes schedule_meeting_tool at top level
├── verify_setup.py                  # Pre-flight checks (env, packages, files)
│
├── requirements.txt
├── .env                             # (gitignored) secrets and config
├── client_secret.json               # (gitignored) Google OAuth client credentials
├── oauth_tokens.json                # (gitignored) per-user Google tokens
└── .gitignore
```

---

## Installation

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | Required for `asyncio.get_running_loop()` and type hint syntax |
| Twilio account | Needs a phone number with Voice capability |
| Google Cloud project | OAuth 2.0 client ID (Desktop or Web app type) |
| OpenAI API key | Must have access to `gpt-4o-realtime-preview` |
| ngrok (or equivalent) | To expose the local server to Twilio and Google |

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/your-username/ai-voice-agent.git
cd ai-voice-agent

# 2. Create and activate a virtual environment
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env   # then fill in your values

# 5. Place Google OAuth credentials at project root
# Download client_secret.json from Google Cloud Console → APIs & Services → Credentials

# 6. Run pre-flight checks
python verify_setup.py
```

---

## Configuration

Create a `.env` file in the project root. All required variables are marked with *.

### Core

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ | — | OpenAI API key (`sk-proj-...`) |
| `TWILIO_ACCOUNT_SID` | ✅ | — | Twilio account SID (`ACxxx...`) |
| `TWILIO_AUTH_TOKEN` | ✅ | — | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | ✅ | — | Your Twilio number in E.164 format |
| `SERVER_HOST` | ✅ | — | Public hostname from ngrok (no scheme, e.g. `abc.ngrok-free.app`) |

### Google OAuth

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_OAUTH_CLIENT_SECRETS` | ✅ | `client_secret.json` | Path to Google OAuth credentials file |
| `GOOGLE_OAUTH_TOKEN_PATH` | — | `oauth_tokens.json` | Path to persisted user tokens |
| `GOOGLE_OAUTH_STATE_SECRET` | — | Falls back to `OPENAI_API_KEY` | HMAC secret for state token signing (set a random string in production) |

### OpenAI Realtime

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_REALTIME_MODEL` | — | `gpt-4o-realtime-preview` | Realtime model name |
| `OPENAI_REALTIME_URL` | — | Auto-built from model | Override the full WebSocket URL |
| `OPENAI_VOICE` | — | `alloy` | TTS voice (`alloy`, `echo`, `shimmer`, etc.) |
| `OPENAI_TEMPERATURE` | — | `0.8` | Response sampling temperature |
| `OPENAI_MAX_TOKENS` | — | `4096` | Max response output tokens |
| `OPENAI_MODALITIES` | — | `audio,text` | Comma-separated list of modalities |
| `OPENAI_INPUT_AUDIO_FORMAT` | — | `g711_ulaw` | `g711_ulaw`, `g711_alaw`, or `pcm16` |
| `OPENAI_OUTPUT_AUDIO_FORMAT` | — | `g711_ulaw` | Same options as input |
| `OPENAI_TURN_DETECTION_TYPE` | — | `server_vad` | Turn detection strategy |

### Barge-in Tuning

| Variable | Required | Default | Description |
|---|---|---|---|
| `BARGE_IN_RMS_THRESHOLD` | — | `120` | RMS energy level to classify as speech |
| `BARGE_IN_TRIGGER_FRAMES` | — | `1` | Consecutive frames above threshold before triggering barge-in |

### Scraper

| Variable | Required | Default | Description |
|---|---|---|---|
| `TARGET_URL` | — | `https://www.wikipedia.org/` | URL to scrape before placing the call |
| `TARGET_PHONE` | — | — | Phone number to call in E.164 format |
| `SCRAPER_TIMEOUT` | — | `10` | HTTP timeout in seconds |
| `SCRAPER_MAX_CHARS` | — | `800` | Max characters of scraped text to inject as context |

### Scheduler

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_SCHEDULER_MODEL` | — | `gpt-4o` | Chat model used by the LangGraph calendar agent |
| `LOG_LEVEL` | — | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Usage

### Step 1 — Start the API server

```bash
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### Step 2 — Expose the server with ngrok

```bash
ngrok http 8000
```

Copy the generated hostname (e.g. `abc123.ngrok-free.app`) into `.env` as `SERVER_HOST`.

### Step 3 — Configure the Twilio webhook

In the Twilio Console, set your phone number's **Voice webhook** to:

```
https://<YOUR_NGROK_DOMAIN>/voice/incoming
```

HTTP method: `POST`

### Step 4 — Connect a user to Google Calendar

Open this URL in a browser and complete the Google consent flow:

```
https://<YOUR_NGROK_DOMAIN>/auth/google/start?user_id=+15551234567
```

- `user_id` must be the caller's E.164 phone number.
- Credentials are saved to `oauth_tokens.json` after consent.

### Step 5 — Place a call

```bash
python graph_scraper.py
```

This scrapes `TARGET_URL`, then initiates a Twilio outbound call to `TARGET_PHONE`. The assistant will introduce itself with context from the scraped page and can schedule meetings on request.

### Pre-flight check

Run this before your first call to catch any missing config or packages:

```bash
python verify_setup.py
```

---

## API Reference

### `GET /healthz`

Basic liveness check.

**Response:**
```json
{ "status": "ok" }
```

---

### `GET|POST /voice/incoming`

Twilio Voice webhook. Returns TwiML that opens a Media Stream WebSocket and passes `scraped_data` and `user_id` as custom stream parameters.

**Query params (GET) / Form body (POST):**

| Parameter | Source | Description |
|---|---|---|
| `data` | Query string | URL-encoded scraped context |
| `From` | Twilio POST body | Caller's phone number |
| `To` / `Called` | Twilio POST body | Called number |

**Response:** `application/xml` (TwiML)

---

### `WS /media-stream`

Twilio Media Stream WebSocket endpoint. Accepts the Twilio streaming protocol and bridges audio bidirectionally with OpenAI Realtime API.

Custom stream parameters read on `start` event:

| Parameter | Description |
|---|---|
| `scraped_data` | Website context injected into the system prompt |
| `user_id` | E.164 phone number used to look up Google OAuth tokens |

---

### `GET /auth/google/start`

Initiates Google OAuth2 PKCE flow for a given user.

**Query params:**

| Parameter | Description |
|---|---|
| `user_id` | Caller's phone number in E.164 format |

**Response:** `302 Redirect` → Google consent screen

---

### `GET /auth/google/callback`

OAuth2 callback. Validates HMAC-signed state, verifies PKCE, exchanges the auth code, and saves credentials.

**Response:** `200 HTML` — confirmation page

---

## Contributing

1. Fork the repository and create a feature branch (`git checkout -b feat/my-feature`).
2. Install dependencies and run `python verify_setup.py` to confirm your environment.
3. Make your changes. Add a test or reproduction script for non-trivial changes.
4. Open a pull request with a clear description of what changed and how to verify it.

Issues and suggestions are welcome via GitHub Issues.

---

## License

License not yet specified. Contact the repository owner for usage rights.
