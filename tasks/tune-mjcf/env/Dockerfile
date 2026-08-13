FROM python:3.13.7-slim-bookworm
WORKDIR /app
RUN pip install --no-cache-dir mujoco==3.3.5
COPY eval.py /app/eval.py
COPY model_ref.xml /app/model_ref.xml
