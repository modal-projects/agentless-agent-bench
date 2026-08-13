FROM ubuntu:24.04
WORKDIR /app
RUN apt-get update  && apt-get install -y --no-install-recommends       python3       python3-pip  && rm -rf /var/lib/apt/lists/*
COPY inputs/ /app/
