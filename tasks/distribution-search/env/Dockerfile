FROM python:3.13.7-slim-bookworm
WORKDIR /app
RUN apt-get update
RUN pip install numpy==2.1.2 scipy==1.15.3

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 numpy==2.3.0 pytest-json-ctrf==0.3.5
COPY tests /tests
