FROM python:3.13.7-slim-bookworm
WORKDIR /app
RUN pip install --no-cache-dir mujoco==3.3.5
COPY eval.py /app/eval.py
COPY model_ref.xml /app/model_ref.xml

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 mujoco==3.3.5 pytest-json-ctrf==0.3.5
COPY tests /tests
