# agentless-agent-bench

Benchmark script for testing host perf for "agentic workloads" by emulating agent terminal behavior with network stubbed out.

This is built on terminal-bench-2.1 task dataset using the `oracle` solutions, which remove LLM-turn latency. This is then filtered down to 51 oracle solutions which use no network. The dockerfiles are then ported to be arm compatible. The environments may then be built in advance of the benchmark.

### Preparation
```bash
uv run main.py build
```
Build all the task images in parallel for the current native platform (override native platform by setting env var `PLATFORM=linux/arm64` or passing `--platform linux/arm64`). 

Running this step ensures that there is no network time in the bench.

```bash
uv run main.py warm --each 3
```
Stand up the warm container pool: one long-lived container per task (x `--each` replicas), defined statically in `docker-compose.yml`. The benchmarks exec `solve.sh` inside these prewarmed containers instead of paying a `docker run` boot per iteration — so they measure the workload, not Docker. After standup, each container's pristine workdir is snapshotted to a tar inside the container; before every solve run the container is reset (stray processes killed, workdir restored) since solve scripts aren't rerun-safe. `warm` is idempotent (re-running never overwrites a baseline); use `--recreate` for a fresh pool and `--down` to tear it down.

### Benchmarking
**Serial:**
```bash
uv run main.py serial
```
Run the oracle solutions one-by-one in the warm pool. Outputs the per-task latency for all 51 tasks into `results/serial_<unix ts>.json`. Latency is measured inside the container around `solve.sh` itself, so it excludes both container boot and docker-exec overhead.

**Throughput:**
```bash
uv run main.py throughput --ncpu 4 --duration 10
```
Runs all 51 tasks concurrently, cycling as many solve runs as possible per task (each preceded by an in-container state reset) within a fixed time window.
Outputs iterations achieved into `results/throughput_<unix ts>.json`.

Args:
- `--ncpu 8` limit pool of CPUs to 8 (default 4)
- `--each 3` run 3 lanes (replicas) per task, e.g. 51x3=153 lanes (default 1; requires `warm --each 3`)
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
