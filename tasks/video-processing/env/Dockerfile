FROM python:3.13.7-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y     libgl1-mesa-glx     libglib2.0-0     libsm6     libxext6     libxrender-dev     libgomp1     && rm -rf /var/lib/apt/lists/*
RUN pip install "opencv-contrib-python>=4.11.0.86"
COPY example_video.mp4 /app/example_video.mp4

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 toml==0.10.2 opencv-contrib-python==4.11.0.86 pytest-json-ctrf==0.3.5
COPY tests /tests
