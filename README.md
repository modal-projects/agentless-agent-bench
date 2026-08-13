# agentless-agent-bench

Benchmark script for testing host perf for "agentic workloads" by emulating agent terminal behavior with network stubbed out.

This is built on terminal-bench-2.1 task dataset using the `oracle` solutions, which remove LLM-turn latency. This is then filtered down to 51 oracle solutions which use no network. The dockerfiles are then ported to be arm compatible. The environments may then be built in advance of the benchmark.

### Preparation
```bash
make build
```
Build all the task images for the current native platform (override with `PLATFORM=linux/arm64`). 

Running this step ensures that there is no network time in the bench.

### Benchmarking
**Serial:**
```bash
make benchmark
```
Run the oracle solutions one-by-one against the locally built images. Outputs the total end-to-end latency for all 51 tasks into `results/benchmark.json`

**Contented:**
```bash
make soak
```
Runs all 51 tasks concurrently, cycling as many runs as possible (including container standup/teardown) per task, within a fixed time window.
Outputs iterations achieved into `results/soak.json`.

Args:
- `make soak NCPUS=8` limit pool of CPUs to 8s (default 4)
- `make soak DURATION=60` limit total run to 60s (default 600s)
