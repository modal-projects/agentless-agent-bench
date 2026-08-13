# agentless-agent-bench

Benchmark script for testing host perf for "agentic workloads" by emulating agent terminal behavior with network stubbed out.

This is built on terminal-bench-2.1 task dataset using the `oracle` solutions, which remove LLM-turn latency. This is then filtered down to oracle solutions which use no network. The environments may then be built in advance of the benchmark.

- `make build` to build the task images from `tasks/<name>/env` so network time does not interfere with the bench. Images build for the host's native architecture (override with `PLATFORM=linux/arm64`).
- `make benchmark` to run the oracle solutions in the locally built images.
