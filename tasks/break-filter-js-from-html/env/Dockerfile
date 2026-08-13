FROM python:3.13.7-slim-bookworm

RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    chromium \
    chromium-driver \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir selenium==4.35.0 beautifulsoup4==4.13.4

WORKDIR /app

COPY filter.py /app/

COPY tests/test_outputs.py /app
