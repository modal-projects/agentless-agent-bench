FROM python:3.11.14-slim-trixie

RUN apt-get update && apt-get install -y \
    tmux \
    asciinema \
    && rm -rf /var/lib/apt/lists/*

RUN pip install pandas==2.2.3 pyarrow==17.0.0

WORKDIR /app

COPY data /data

ENV PYTHONPATH=/app:
