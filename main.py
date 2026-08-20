"""
  uv run main.py build
  uv run main.py warm --each 3
  uv run main.py serial
  uv run main.py throughput --ncpu 4 --duration 10
  uv run main.py throughput-ramp
  uv run main.py warm --down
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

ROOT = Path(__file__).resolve().parent
console = Console()
errcon = Console(stderr=True)

DEVNULL = subprocess.DEVNULL

COMPOSE_FILE = ROOT / "docker-compose.yml"
BASELINE = "/var/tmp/baseline.tar"
BASELINE_EXTRA = "/var/tmp/baseline-extra.tar"


def load_tasks(only: list[str] | None = None) -> list[dict]:
    tasks = json.loads((ROOT / "tasks.json").read_text())
    tasks = [t for t in tasks if (ROOT / "tasks" / t["name"] / "env").is_dir()]
    if only:
        tasks = [t for t in tasks if t["name"] in only]
    return tasks


async def _run_procs(cmds: list[tuple[str, list[str]]], progress: Progress, bar) -> list[tuple[str, int, str]]:
    """Run (key, argv) commands concurrently -> (key, returncode, merged output) each."""
    async def run_one(key: str, argv: list[str]) -> tuple[str, int, str]:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        progress.advance(bar)
        return key, proc.returncode or 0, out.decode(errors="replace")

    return await asyncio.gather(*(run_one(k, a) for k, a in cmds))


# ---------------------------------------------------------------- build

def cmd_build(args: argparse.Namespace) -> int:
    platform = args.platform or os.environ.get("PLATFORM")
    if not platform:
        arch = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Arch}}"],
            capture_output=True, text=True,
        ).stdout.strip() or "amd64"
        platform = f"linux/{arch}"
    names = [t["name"] for t in load_tasks(args.only)]
    errcon.print(f"building {len(names)} images for {platform}")

    cmds = [
        (n, ["docker", "build", "--platform", platform,
             "-t", f"local/{n}", str(ROOT / "tasks" / n / "env")])
        for n in names
    ]
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]build"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        bar = progress.add_task("build", total=len(names))
        results = asyncio.run(_run_procs(cmds, progress, bar))

    failed = [(n, rc, out) for n, rc, out in results if rc != 0]
    log_dir = ROOT / "logs" / "build"
    for n, rc, out in failed:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"{n}.log").write_text(out)
        tail = "\n".join(out.splitlines()[-20:])
        errcon.print(f"\n[red bold]FAIL[/] {n} (exit {rc}) — full log in logs/build/{n}.log")
        errcon.print(tail, highlight=False)

    ok = len(results) - len(failed)
    console.print(f"[green]{ok} built[/]" + (f", [red]{len(failed)} failed[/]" if failed else ""))
    return 1 if failed else 0


# ----------------------------------------------------------------- warm
# prepare all environments as running containers and prep a snapshot of their initial state
# this is to make benchmarks not measure docker start/stop overhead

def reset_script(task: dict) -> str:
    """Restore a container to its baseline: kill every process except PID 1
    (the compose keepalive/reaper shell) and this shell, then re-extract the
    workdir (and any reset_paths) from the warm-time tar snapshot."""
    lines = [
        "reset_state() {",
        "kill -9 -- -1 2>/dev/null",
        'if [ "$PWD" != / ]; then find "$PWD" -mindepth 1 -delete || return 1; fi',
        f'tar -xpf {BASELINE} -C "$PWD" || return 1',
    ]
    if paths := task.get("reset_paths"):
        lines += [
            f'rm -rf {" ".join(paths)} || return 1',
            f"if [ -f {BASELINE_EXTRA} ]; then tar -xpf {BASELINE_EXTRA} -C / || return 1; fi",
        ]
    lines += ["}", "reset_state >/dev/null 2>&1"]
    return "\n".join(lines)


# post-window cleanup: only reap stray processes. No fs restore here — every
# solve (throughput iteration or serial run) restores state before running,
# so restoring at window end would just repeat the most expensive resets.
KILL_STRAYS = "kill -9 -- -1 2>/dev/null; true"


# solve.sh timed inside the container
# to not measure the 30-60ms docker exec client overhead
SOLVE_TIMED = """t0=$(date +%s%N)
bash /solution/solve.sh
rc=$?
t1=$(date +%s%N)
printf '\\n@@BENCH_MS %s\\n' $(( (t1 - t0) / 1000000 ))
exit $rc"""


def discover_pool() -> dict[str, list[str]]:
    """Map task name -> warm container names, ordered by replica number."""
    fmt = '{{.Names}}\t{{.Label "com.docker.compose.service"}}\t{{.Label "com.docker.compose.container-number"}}'
    out = subprocess.run(
        ["docker", "ps",
         "--filter", "label=com.docker.compose.project=agentless-bench",  # `name:` in docker-compose.yml
         "--format", fmt],
        capture_output=True, text=True,
    ).stdout
    pool: dict[str, list[tuple[int, str]]] = {}
    for line in out.splitlines():
        name, service, number = line.split("\t")
        pool.setdefault(service, []).append((int(number), name))
    return {s: [name for _, name in sorted(v)] for s, v in pool.items()}


def require_pool(tasks: list[dict], each: int) -> dict[str, list[str]]:
    pool = discover_pool()
    missing = [t["name"] for t in tasks if len(pool.get(t["name"], [])) < each]
    if missing:
        errcon.print(f"[red]no warm container (x{each}) for:[/] {' '.join(missing)}")
        errcon.print(f"start the pool first: uv run main.py warm --each {each}")
        raise SystemExit(1)
    return pool


def docker_update(ctrs: list[str], cpuset: str, quota: int) -> None:
    """Retune cpu limits on running containers; quota -1 = unlimited.
    Always the period/quota pair, never --cpus (NanoCPUs can't be unset)."""
    res = subprocess.run(
        ["docker", "update", "--cpuset-cpus", cpuset,
         "--cpu-period", "100000", "--cpu-quota", str(quota), *ctrs],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        errcon.print(f"[red]docker update failed:[/] {res.stderr.strip()}")
        raise SystemExit(1)


def cmd_warm(args: argparse.Namespace) -> int:
    if args.down:
        return subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "--remove-orphans"],
        ).returncode
    if args.each < 1:
        errcon.print(f"--each {args.each} must be >= 1")
        return 1

    up = ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--wait"]
    if args.recreate:
        up.append("--force-recreate")
    errcon.print(f"warming pool: {len(load_tasks())} tasks x {args.each}")
    rc = subprocess.run(up, env={**os.environ, "WARM_EACH": str(args.each)}).returncode
    if rc != 0:
        errcon.print("[red]compose up failed[/] (missing images? run: uv run main.py build)")
        return rc

    # snapshot each container's pristine state; skip if a baseline already
    # exists, so re-running warm on a used pool never captures dirty state.
    # reset_paths outside the workdir go into a second tar — only those that
    # exist at warm time (absent ones are restored by rm -rf alone).
    tasks = {t["name"]: t for t in load_tasks()}
    cmds = []
    for name, ctrs in sorted(discover_pool().items()):
        if name not in tasks:
            continue
        script = [
            f"if [ -f {BASELINE} ]; then exit 0; fi",
            f'tar -cpf {BASELINE} -C "$PWD" . || exit 1',
        ]
        if paths := tasks[name].get("reset_paths"):
            script += [
                'ex=""',
                f'for p in {" ".join(paths)}; do if [ -e "$p" ]; then ex="$ex ${{p#/}}"; fi; done',
                f"if [ -n \"$ex\" ]; then tar -cpf {BASELINE_EXTRA} -C / $ex || exit 1; fi",
            ]
        cmds += [(ctr, ["docker", "exec", ctr, "bash", "-c", "\n".join(script)]) for ctr in ctrs]

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]snapshot"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        bar = progress.add_task("snapshot", total=len(cmds))
        results = asyncio.run(_run_procs(cmds, progress, bar))

    failed = [(c, rc, out) for c, rc, out in results if rc != 0]
    for c, rc, out in failed:
        errcon.print(f"[red bold]FAIL[/] snapshot {c} (exit {rc})")
        errcon.print("\n".join(out.splitlines()[-5:]), highlight=False)
    ok = len(results) - len(failed)
    console.print(f"[green]{ok} containers ready[/]" + (f", [red]{len(failed)} snapshot failures[/]" if failed else ""))
    return 1 if failed else 0


# --------------------------------------------------------------- serial

def cmd_serial(args: argparse.Namespace) -> int:
    tasks = load_tasks(args.only)
    pool = require_pool(tasks, 1)
    nproc = os.cpu_count() or 1
    (ROOT / "logs").mkdir(exist_ok=True)
    results_path = Path(args.results) if args.results else ROOT / "results" / f"serial_{int(time.time())}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)

    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        bar = progress.add_task("serial", total=len(tasks))
        for t in tasks:
            name = t["name"]
            ctr = pool[name][0]
            progress.update(bar, description=f"[bold]{name}")
            docker_update([ctr], f"0-{nproc - 1}", int(t["cpus"] * 100_000))
            reset_rc = subprocess.run(
                ["docker", "exec", ctr, "bash", "-c", reset_script(t)],
                stdout=DEVNULL, stderr=DEVNULL,
            ).returncode
            if reset_rc != 0:
                errcon.print(f"[red]reset failed[/] for {name} (exit {reset_rc}); skipping solve")
                results.append({"task": name, "exit_code": 99, "ms": 0})
                progress.advance(bar)
                continue
            start = time.monotonic()
            proc = subprocess.run(
                ["docker", "exec", ctr, "bash", "-c", SOLVE_TIMED],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            wall_ms = round((time.monotonic() - start) * 1000)
            # pull the @@BENCH_MS marker (and the newline its printf prepended)
            # off the end of the output; the rest is the solve log
            log = proc.stdout
            idx = log.rfind(b"@@BENCH_MS ")
            marker = log[idx:].split() if idx != -1 else []
            if len(marker) > 1 and marker[1].isdigit():
                ms = int(marker[1])
                log = log[:idx].removesuffix(b"\n")
            else:
                errcon.print(f"{name}: no timing marker; recording wall clock (incl. exec overhead)")
                ms = wall_ms
            (ROOT / "logs" / f"{name}.log").write_bytes(log)
            results.append({"task": name, "exit_code": proc.returncode, "ms": ms})
            progress.advance(bar)
        progress.update(bar, description="[bold]serial")

    results_path.write_text(json.dumps(results, indent=2) + "\n")

    table = Table(title="serial (warm pool)")
    table.add_column("task")
    table.add_column("exit", justify="right")
    table.add_column("ms", justify="right")
    for r in results:
        exit_style = "green" if r["exit_code"] == 0 else "red bold"
        table.add_row(r["task"], f"[{exit_style}]{r['exit_code']}[/]", f"{r['ms']}")
    console.print(table)
    console.print(f"wrote {results_path}")
    return 1 if any(r["exit_code"] != 0 for r in results) else 0


# ----------------------------------------------------------- throughput

def _throughput_lane(task: dict, ctr: str, deadline: float, tally: dict) -> None:
    # one iteration = reset (rc 99 on failure), then solve capped at the window
    # deadline by an in-container timeout (a docker exec can't be killed from
    # outside). Deadline checks bracket the reset so a slow reset (wipe + untar
    # of a large workdir) is never started for a window that is already over.
    dl = int(deadline)
    script = "\n".join([
        f"if [ $(date +%s) -ge {dl} ]; then exit 124; fi",
        reset_script(task) + " || exit 99",
        f"rem=$(( {dl} - $(date +%s) ))",
        'if [ "$rem" -le 0 ]; then exit 124; fi',
        'exec timeout -s KILL "$rem" bash /solution/solve.sh',
    ])
    reset_failed = False
    while (now := time.time()) < deadline:
        proc = subprocess.Popen(
            ["docker", "exec", ctr, "bash", "-c", script],
            stdout=DEVNULL, stderr=DEVNULL,
        )
        try:
            # the in-container checks/timeout enforce the deadline; the short
            # grace only cuts an exec whose in-flight reset outlives the window
            # (the half-reset fs self-heals on the next iteration's reset)
            rc = proc.wait(timeout=deadline - now + 3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            break  # straggler in the container is reaped by the post-window reset
        if rc == 0:
            tally["completed"] += 1
            reset_failed = False
        elif rc in (124, 137) and time.time() >= deadline - 0.5:
            break  # cut off by the in-container timeout at the deadline
        elif rc == 99:
            if reset_failed:
                errcon.print(f"[red]{task['name']}: reset keeps failing on {ctr}; abandoning lane[/]")
                break
            reset_failed = True
            subprocess.run(["docker", "restart", "-t", "0", ctr], stdout=DEVNULL, stderr=DEVNULL)
        elif rc in (125, 126, 127):
            errcon.print(f"[red]{task['name']}: docker exec error (exit {rc}) on {ctr}; abandoning lane[/]")
            break
        elif time.time() < deadline:
            tally["failed"] += 1


def run_throughput(tasks: list[dict], pool: dict[str, list[str]], ncpu: int,
                   duration: int, title: str = "throughput", each: int = 1) -> dict:
    """One throughput run: `each` lanes per task cycling until the deadline. Returns the summary dict."""
    cpuset = f"0-{ncpu - 1}"
    # one container and tally per lane so replicas never share state across threads
    lanes = [(t, pool[t["name"]][i], {"completed": 0, "failed": 0}) for t in tasks for i in range(each)]
    docker_update([c for _, c, _ in lanes], cpuset, -1)
    start = int(time.time())
    deadline = start + duration
    errcon.print(
        f"throughput: ncpu={ncpu} (cpuset {cpuset})  duration={duration}s  "
        f"{len(lanes)} lanes"
        + (f" ({len(tasks)} tasks x {each})" if each > 1 else "")
    )

    threads = [
        threading.Thread(target=_throughput_lane, args=(t, ctr, deadline, tally), daemon=True)
        for t, ctr, tally in lanes
    ]

    def counts() -> dict:
        agg = {t["name"]: {"completed": 0, "failed": 0} for t in tasks}
        for t, _, tally in lanes:
            agg[t["name"]]["completed"] += tally["completed"]
            agg[t["name"]]["failed"] += tally["failed"]
        return agg

    progress = Progress(
        TextColumn(f"[bold]{title}"),
        BarColumn(bar_width=None),
        TextColumn("{task.completed:>4.0f}/{task.total:.0f}s"),
        console=console,
    )
    bar = progress.add_task(title, total=duration)

    def counts_table() -> Table:
        agg = counts()
        names = sorted(agg)
        rows_fit = max(5, console.size.height - 8)
        ngroups = max(1, math.ceil(len(names) / rows_fit))
        nrows = math.ceil(len(names) / ngroups)
        table = Table(pad_edge=False)
        for _ in range(ngroups):
            table.add_column("task", no_wrap=True)
            table.add_column("completed", justify="right")
            table.add_column("failed", justify="right")
        for r in range(nrows):
            cells: list[str] = []
            for g in range(ngroups):
                i = g * nrows + r
                if i < len(names):
                    n = names[i]
                    c = agg[n]
                    fail = f"[red]{c['failed']}[/]" if c["failed"] else "[dim]0[/]"
                    cells += [n, f"[green]{c['completed']}[/]", fail]
                else:
                    cells += ["", "", ""]
            table.add_row(*cells)
        return table

    def render() -> Group:
        progress.update(bar, completed=min(time.time() - start, duration))
        return Group(progress, counts_table())

    try:
        for th in threads:
            th.start()
        with Live(render(), console=console, refresh_per_second=4) as live:
            while any(th.is_alive() for th in threads):
                time.sleep(0.25)
                live.update(render())
            live.update(render())
    finally:
        # reap any straggler process cut off at the deadline (solve or reset)
        procs = [
            (ctr, subprocess.Popen(["docker", "exec", ctr, "bash", "-c", KILL_STRAYS],
                                   stdout=DEVNULL, stderr=DEVNULL))
            for _, ctr, _ in lanes
        ]
        for ctr, p in procs:
            if p.wait() != 0:
                subprocess.run(["docker", "restart", "-t", "0", ctr], stdout=DEVNULL, stderr=DEVNULL)

    elapsed = int(time.time()) - start
    final = counts()
    per_task = [{"task": n, **final[n]} for n in final]
    per_task.sort(key=lambda r: -r["completed"])
    return {
        "ncpus": ncpu,
        "each": each,
        "seconds": elapsed,
        "total_completed": sum(r["completed"] for r in per_task),
        "total_failed": sum(r["failed"] for r in per_task),
        "tasks": per_task,
    }


def cmd_throughput(args: argparse.Namespace) -> int:
    avail = os.cpu_count() or 1
    if args.ncpu > avail:
        errcon.print(f"--ncpu {args.ncpu} exceeds available CPUs ({avail}); pick <= {avail}")
        return 1
    if args.each < 1:
        errcon.print(f"--each {args.each} must be >= 1")
        return 1

    tasks = load_tasks(args.only)
    if not tasks:
        errcon.print("no tasks selected")
        return 1
    pool = require_pool(tasks, args.each)

    log_dir = ROOT / "throughput_logs"
    log_dir.mkdir(exist_ok=True)
    for old in log_dir.glob("*.tsv"):
        old.unlink()
    results_path = Path(args.results) if args.results else ROOT / "results" / f"throughput_{int(time.time())}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)

    summary = run_throughput(tasks, pool, args.ncpu, args.duration, each=args.each)

    lines = []
    for r in sorted(summary["tasks"], key=lambda r: r["task"]):
        line = f"{r['task']}\t{r['completed']}\t{r['failed']}"
        (log_dir / f"{r['task']}.tsv").write_text(line + "\n")
        lines.append(line)
    (log_dir / "all.tsv").write_text("\n".join(lines) + "\n" if lines else "")

    results_path.write_text(json.dumps(summary, indent=2) + "\n")

    console.print(
        f"ncpu={summary['ncpus']}  elapsed={summary['seconds']}s  "
        f"total_completed=[green]{summary['total_completed']}[/]  "
        f"total_failed=[red]{summary['total_failed']}[/]"
    )
    console.print(f"wrote {results_path}")
    return 0


# ------------------------------------------------------ throughput-ramp

def cmd_throughput_ramp(args: argparse.Namespace) -> int:
    nproc = os.cpu_count() or 1
    # light-exponential core counts from 1 to nproc, always ending at nproc
    schedule = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 20, 26, 32]
    while schedule[-1] < nproc:
        schedule.append(math.ceil(schedule[-1] * 1.25))
    schedule = [s for s in schedule if s <= nproc]
    if schedule[-1] != nproc:
        schedule.append(nproc)
    if args.max_each < 1:
        errcon.print(f"--max-each {args.max_each} must be >= 1")
        return 1

    tasks = load_tasks(args.only)
    if not tasks:
        errcon.print("no tasks selected")
        return 1
    pool = require_pool(tasks, args.max_each)

    results_path = Path(args.results) if args.results else ROOT / "results" / f"throughput_ramp_{int(time.time())}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    errcon.print(
        f"ramp: {len(schedule)} cpu steps {schedule} x each=1..{args.max_each}  "
        f"duration={args.duration}s/step"
    )

    plan = [(e, n) for e in range(1, args.max_each + 1) for n in schedule]
    steps: list[dict] = []
    interrupted = False
    try:
        for i, (e, n) in enumerate(plan):
            errcon.print(f"ramp step {i + 1}/{len(plan)}: ncpu={n} each={e}")
            steps.append(run_throughput(tasks, pool, n, args.duration,
                                        title=f"ncpu={n} each={e}", each=e))
            if i < len(plan) - 1:
                time.sleep(args.cooldown)
    except KeyboardInterrupt:
        interrupted = True
        errcon.print("interrupted — writing completed steps")

    if not steps:
        return 130 if interrupted else 1

    ramp = {
        "nproc": nproc,
        "max_each": args.max_each,
        "duration": args.duration,
        "cooldown": args.cooldown,
        "interrupted": interrupted,
        "schedule": schedule,
        "steps": steps,
    }
    results_path.write_text(json.dumps(ramp, indent=2) + "\n")

    table = Table(title=f"throughput ramp (warm pool, {args.duration}s/step)")
    table.add_column("each", justify="right")
    table.add_column("ncpu", justify="right")
    table.add_column("completed", justify="right")
    table.add_column("failed", justify="right")
    for s in steps:
        table.add_row(str(s["each"]), str(s["ncpus"]),
                      f"[green]{s['total_completed']}[/]", f"[red]{s['total_failed']}[/]")
    console.print(table)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(palette="colorblind")
    fig, ax = plt.subplots()
    for each in sorted({s["each"] for s in steps}):
        line = [s for s in steps if s["each"] == each]
        lanes = len(line[0]["tasks"]) * each
        sns.lineplot(
            x=[s["ncpus"] for s in line],
            y=[s["total_completed"] for s in line],
            marker="o", linewidth=2, markersize=8,
            label=f"{lanes} concurrent containers", ax=ax,
        )
    ax.set_xticks(sorted({s["ncpus"] for s in steps}))
    ax.set_ylim(0, max(max(s["total_completed"] for s in steps), 1) * 1.1)
    ax.set_xlabel("cores (cpuset size)")
    ax.set_ylabel(f"runs completed in {args.duration}s")
    ax.set_title("throughput ramp")
    plot_path = results_path.with_suffix(".png")
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    console.print(f"wrote {results_path}")
    console.print(f"wrote {plot_path}")
    return 130 if interrupted else 0


# ----------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--only", nargs="*", default=os.environ.get("ONLY", "").split() or None,
                       help="restrict to these task names")

    p_build = sub.add_parser("build", help="build all task images in parallel")
    common(p_build)
    p_build.add_argument("--platform", default=None,
                         help="docker --platform (default: $PLATFORM or native)")
    p_build.set_defaults(fn=cmd_build)

    p_warm = sub.add_parser("warm", help="stand up the warm container pool (docker compose) and snapshot baselines")
    p_warm.add_argument("--each", type=int, default=int(os.environ.get("WARM_EACH", 1)),
                        help="replicas per task (throughput lanes need one each)")
    p_warm.add_argument("--recreate", action="store_true",
                        help="force-recreate the containers (fresh baselines)")
    p_warm.add_argument("--down", action="store_true", help="tear the pool down instead")
    p_warm.set_defaults(fn=cmd_warm)

    p_serial = sub.add_parser("serial", help="run oracle solutions serially in the warm pool, record latency")
    common(p_serial)
    p_serial.add_argument("--results", default=os.environ.get("SERIAL_RESULTS"),
                          help="output path (default: results/serial_<unix ts>.json)")
    p_serial.set_defaults(fn=cmd_serial)

    p_tput = sub.add_parser("throughput", help="one lane per warm container, cycle runs until the deadline")
    common(p_tput)
    p_tput.add_argument("--ncpu", type=int, default=int(os.environ.get("NCPUS", 4)))
    p_tput.add_argument("--each", type=int, default=int(os.environ.get("EACH", 1)),
                        help="lanes (replicas) per task")
    p_tput.add_argument("--duration", type=int, default=int(os.environ.get("DURATION", 20)),
                        help="seconds to run")
    p_tput.add_argument("--results", default=os.environ.get("THROUGHPUT_RESULTS"),
                        help="output path (default: results/throughput_<unix ts>.json)")
    p_tput.set_defaults(fn=cmd_throughput)

    p_ramp = sub.add_parser("throughput-ramp", help="throughput at ramping ncpu (1..nproc), plot completed vs cores")
    common(p_ramp)
    p_ramp.add_argument("--max-each", type=int, default=int(os.environ.get("RAMP_MAX_EACH", 3)),
                        help="sweep each=1..N lanes per task, one plot line per value")
    p_ramp.add_argument("--duration", type=int, default=int(os.environ.get("RAMP_DURATION", 10)),
                        help="seconds per step")
    p_ramp.add_argument("--cooldown", type=int, default=int(os.environ.get("RAMP_COOLDOWN", 2)),
                        help="seconds between steps")
    p_ramp.add_argument("--results", default=os.environ.get("RAMP_RESULTS"),
                        help="output path (default: results/throughput_ramp_<unix ts>.json)")
    p_ramp.set_defaults(fn=cmd_throughput_ramp)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
