# agentless-agent-bench

Benchmark script for testing host perf for "agentic workloads" by emulating agent terminal behavior with network stubbed out.

This is built on terminal-bench-2.1 task dataset using the `oracle` solutions, which remove LLM-turn latency. This is then filtered down to 51 oracle solutions which use no network. The dockerfiles are then ported to be arm compatible. The environments may then be built in advance of the benchmark.

### Preparation
```bash
uv run main.py build
```
Build all the task images in parallel for the current native platform (override native platform by setting env var `PLATFORM=linux/arm64` or passing `--platform linux/arm64`). 

Running this step ensures that there is no network time in the bench.

### Benchmarking
**Serial:**
```bash
uv run main.py benchmark
```
Run the oracle solutions one-by-one against the locally built images. Outputs the per-task latency for all 51 tasks into `results/benchmark.json`

**Contented:**
```bash
uv run main.py soak --ncpu 4 --duration 10
```
Runs all 51 tasks concurrently, cycling as many runs as possible (including container standup/teardown) per task, within a fixed time window.
Outputs iterations achieved into `results/soak.json`.

Args:
- `--ncpu 8` limit pool of CPUs to 8 (default 4)
- `--duration 60` limit total run to 60s (default 20s)
