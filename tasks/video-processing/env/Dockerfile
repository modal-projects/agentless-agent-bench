FROM python:3.13.7-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y     libgl1-mesa-glx     libglib2.0-0     libsm6     libxext6     libxrender-dev     libgomp1     && rm -rf /var/lib/apt/lists/*
RUN pip install "opencv-contrib-python>=4.11.0.86"
COPY example_video.mp4 /app/example_video.mp4
