FROM ubuntu:24.04
WORKDIR /app
RUN apt-get update && apt-get install -y gcc g++ curl zlib1g-dev libjpeg-dev
COPY orig.c /app
RUN gcc -static -O3 -o mystery /app/orig.c -lm
RUN rm /app/orig.c

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 pillow==11.2.1 numpy==2.3.1 pytest-json-ctrf==0.3.5
COPY tests /tests
