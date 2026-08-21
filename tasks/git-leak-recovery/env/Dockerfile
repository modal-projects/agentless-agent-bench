FROM ubuntu:24.04
WORKDIR /app
RUN apt-get update && apt-get install -y git
RUN mkdir -p /app && chmod 755 /app
COPY challenge-setup.sh /app/challenge-setup.sh
RUN chmod +x /app/challenge-setup.sh && \
    bash /app/challenge-setup.sh && \
    rm /app/challenge-setup.sh

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 pytest-json-ctrf==0.3.5
COPY tests /tests
