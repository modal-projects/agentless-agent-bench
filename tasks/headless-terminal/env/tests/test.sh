#!/bin/bash
# terminal-bench 2.1 verifier (vendored); deps baked into the image at build
# (pip: pytest/requests, apt: vim) so verification runs with no network.
mkdir -p /logs/verifier
exec pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
