FROM ubuntu:24.04
RUN apt-get update && apt-get install -y nodejs npm gcc
COPY task-deps/hi.c /app/
RUN gcc /app/hi.c -o /app/a.out
WORKDIR /app
