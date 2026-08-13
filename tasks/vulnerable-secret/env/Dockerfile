FROM python:3.13.7-slim-bookworm
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY vulnerable.c .
RUN gcc -o vulnerable vulnerable.c -fno-stack-protector -no-pie -O2 -s
RUN chmod +x vulnerable
RUN rm vulnerable.c
