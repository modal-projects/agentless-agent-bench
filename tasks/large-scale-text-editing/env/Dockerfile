FROM python:3.13.7-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y vim && rm -rf /var/lib/apt/lists/*
COPY gen_large_csv.py /app/
RUN python3 /app/gen_large_csv.py both && rm /app/gen_large_csv.py

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 pytest-json-ctrf==0.3.5
COPY tests /tests
