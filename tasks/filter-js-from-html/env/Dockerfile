FROM python:3.13.7-slim-bookworm
RUN apt-get update && apt-get install -y chromium chromium-driver && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir selenium==4.35.0 beautifulsoup4==4.13.4
WORKDIR /app

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 selenium==4.38.0 bs4==0.0.2 pytest-json-ctrf==0.3.5
COPY tests /tests
ENV SE_OFFLINE=true
