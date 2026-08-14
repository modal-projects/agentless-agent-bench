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
uv run main.py serial
```
Run the oracle solutions one-by-one against the locally built images. Outputs the per-task latency for all 51 tasks into `results/serial_<unix ts>.json`

**Throughput:**
```bash
uv run main.py throughput --ncpu 4 --duration 10
```
Runs all 51 tasks concurrently, cycling as many runs as possible (including container standup/teardown) per task, within a fixed time window.
Outputs iterations achieved into `results/throughput_<unix ts>.json`.

Args:
- `--ncpu 8` limit pool of CPUs to 8 (default 4)
- `--each 3` run 3 lanes (replicas) per task, e.g. 51x3=153 lanes (default 1)
- `--duration 60` limit total run to 60s (default 20s)

**Throughput ramp:**
```bash
uv run main.py throughput-ramp
```
Sweeps the throughput run from 1 core up to all cores on a light-exponential schedule, at a fixed duration per core — once per replica count from each=1 up to `--max-each`. Writes every step's summary into `results/throughput_ramp_<unix ts>.json` and plots total completed runs vs cores to `results/throughput_ramp_<unix ts>.png`, one line per replica count (legend shows concurrent container count, e.g. 51/102/153).

Args:
- `--max-each 3` sweep lanes (replicas) per task from 1 to 3 (default 3)
- `--duration 10` seconds per step (default 10)
- `--cooldown 2` seconds between steps (default 2)
