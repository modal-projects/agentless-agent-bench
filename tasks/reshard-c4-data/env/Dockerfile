FROM python:3.13.7-slim-bookworm
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /bin/
COPY setup.py ./
RUN uv run setup.py
RUN rm setup.py

# ---- terminal-bench 2.1 verifier (baked, offline) ----
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/tb-uv
RUN tb-uv venv -p 3.13 /opt/verifier && tb-uv pip install -p /opt/verifier/bin/python pytest==8.4.1 datasets==3.6.0 tqdm==4.67.1 pytest-json-ctrf==0.3.5
RUN pip install tqdm==4.67.1
RUN /opt/verifier/bin/python -c "from huggingface_hub import hf_hub_download; hf_hub_download('allenai/c4', 'en/c4-train.00009-of-01024.json.gz', repo_type='dataset', local_dir='/opt/c4')"
RUN /opt/verifier/bin/python -c "from datasets import load_dataset; load_dataset('json', data_files={'train': ['/opt/c4/en/c4-train.00009-of-01024.json.gz']}, split='train')"
COPY tests /tests
ENV HF_DATASETS_OFFLINE=1 HF_HUB_OFFLINE=1
