FROM ubuntu:24.04
WORKDIR /app

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python --extra-index-url https://download.pytorch.org/whl/cpu pytest==8.4.1 torch==2.7.0 pytest-json-ctrf==0.3.5
COPY tests /tests
