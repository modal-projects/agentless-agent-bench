FROM ubuntu:24.04
RUN apt-get update && apt-get install -y nodejs npm gcc
COPY task-deps/hi.c /app/
RUN gcc /app/hi.c -o /app/a.out
WORKDIR /app

# ---- terminal-bench 2.1 verifier (baked, offline) ----
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 pytest-json-ctrf==0.3.5
COPY tests /tests
