#!/bin/bash
# terminal-bench 2.1 verifier (vendored); python deps baked into
# /opt/verifier at image build so verification runs with no network.
mkdir -p /logs/verifier
export PATH="/opt/verifier/bin:$PATH"
cp /tests/test.py /app/test.py
exec pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
