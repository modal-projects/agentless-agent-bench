FROM python:3.13.7-slim-bookworm

WORKDIR /app

RUN apt-get update
RUN apt-get install -y gcc

COPY tests/sim.c /app
COPY gates.txt /app
