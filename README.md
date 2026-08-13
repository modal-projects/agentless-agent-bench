# agentless-agent-bench

Benchmark script for testing host perf for "agentic workloads" by emulating agent terminal behavior with network stubbed out.

This is built on terminal-bench-2.1 task dataset using the `oracle` solutions, which remove LLM-turn latency. This is then filtered down to oracle solutions which use no network. The environments may then be built in advance of the benchmark.

- `make build` to build the task images from `tasks/<name>/env` so network time does not interfere with the bench. Images build for the host's native architecture (override with `PLATFORM=linux/arm64`).
- `make benchmark` to run the oracle solutions once each in the locally built images (latency: how fast is one task on an idle box).
- `make soak` for the concurrency benchmark (throughput: how much load a box sustains). One lane per task runs its oracle back-to-back — full container standup/teardown each cycle — with all lanes running at once for a fixed window, so ~`n_tasks` heterogeneous containers stay live. Every lane is pinned to the same `NCPUS`-core budget via `--cpuset-cpus`, so the completion counts compare fairly across machines regardless of total core count. Params: `NCPUS` (cores to pin to, default 8; must be ≤ available), `DURATION` (seconds, default 600), `ONLY` (space-separated subset of tasks). Writes per-task and aggregate completion counts to `soak_results.json`. Example: `make soak NCPUS=8 DURATION=600`.
