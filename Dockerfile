FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY app ./app
COPY static ./static

EXPOSE 8000

# $PORT is injected by Render (and most PaaS); falls back to 8000 locally.
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}
