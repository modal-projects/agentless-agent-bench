FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y coq && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY partial_proof.v /workspace/plus_comm.v

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 pytest-json-ctrf==0.3.5
COPY tests /tests
