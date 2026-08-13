FROM python:3.13.7-slim-bookworm
WORKDIR /app
RUN apt-get update -y && apt-get install -y tmux screen expect
COPY base_terminal.py /app/base_terminal.py
COPY headless_terminal.py /oracle/headless_terminal.py
