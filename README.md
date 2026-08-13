# agentless-agent-bench

Benchmark script for testing host perf for "agentic workloads" by emulating agent terminal behavior with network stubbed out.

This is built on terminal-bench-2.1 task dataset using the `oracle` solutions, which remove LLM-turn latency. This is then filtered down to oracle solutions which use no network. The environments may then be downloaded in advance of the benchmark.

- `make download` to predownload docker images so the network time does not interfere with the bench.
- `make benchmark` to run the oracle solutions.
