FROM python:3.13.7-slim-bookworm
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY vulnerable.c .
RUN gcc -o vulnerable vulnerable.c -fno-stack-protector -no-pie -O2 -s
RUN chmod +x vulnerable
RUN rm vulnerable.c

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 pytest-json-ctrf==0.3.5
COPY tests /tests
