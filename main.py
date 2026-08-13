"""
  uv run main.py build
  uv run main.py benchmark
  uv run main.py soak --ncpu 4 --duration 10
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


def load_tasks(only: list[str] | None = None) -> list[dict]:
    tasks = json.loads((ROOT / "tasks.json").read_text())
    tasks = [t for t in tasks if (ROOT / "tasks" / t["name"] / "env").is_dir()]
    if only:
        tasks = [t for t in tasks if t["name"] in only]
    return tasks


def default_platform() -> str:
    if env := os.environ.get("PLATFORM"):
        return env
    arch = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Arch}}"],
        capture_output=True, text=True,
    ).stdout.strip() or "amd64"
    return f"linux/{arch}"


def resolve_platform(args: argparse.Namespace) -> str:
    return args.platform or default_platform()


# ---------------------------------------------------------------- build

async def _build_one(name: str, platform: str, progress: Progress, bar) -> tuple[str, int, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker", "build", "--platform", platform,
        "-t", f"local/{name}", str(ROOT / "tasks" / name / "env"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    progress.advance(bar)
    return name, proc.returncode or 0, out.decode(errors="replace")


async def _build_all(names: list[str], platform: str, progress: Progress, bar):
    return await asyncio.gather(*(_build_one(n, platform, progress, bar) for n in names))


def cmd_build(args: argparse.Namespace) -> int:
    platform = resolve_platform(args)
    names = [t["name"] for t in load_tasks(args.only)]
    errcon.print(f"building {len(names)} images for {platform}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]build"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        bar = progress.add_task("build", total=len(names))
        results = asyncio.run(_build_all(names, platform, progress, bar))

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


# ------------------------------------------------------------ benchmark

def cmd_benchmark(args: argparse.Namespace) -> int:
    platform = resolve_platform(args)
    tasks = load_tasks(args.only)
    (ROOT / "logs").mkdir(exist_ok=True)
    results_path = Path(args.results)
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
        bar = progress.add_task("benchmark", total=len(tasks))
        for t in tasks:
            name = t["name"]
            progress.update(bar, description=f"[bold]{name}")
            with open(ROOT / "logs" / f"{name}.log", "wb") as log:
                start = time.monotonic()
                rc = subprocess.run(
                    [
                        "docker", "run", "--rm",
                        "--platform", platform,
                        "--network", args.network,
                        "--cpus", str(t["cpus"]),
                        "--memory", f"{t['memory_mb']}m",
                        "-v", f"{ROOT}/tasks/{name}:/solution:ro",
                        f"local/{name}", "bash", "/solution/solve.sh",
                    ],
                    stdout=log, stderr=subprocess.STDOUT,
                ).returncode
                ms = round((time.monotonic() - start) * 1000)
            results.append({"task": name, "exit_code": rc, "ms": ms})
            progress.advance(bar)
        progress.update(bar, description="[bold]benchmark")

    results_path.write_text(json.dumps(results, indent=2) + "\n")

    table = Table(title=f"benchmark ({platform}, network={args.network})")
    table.add_column("task")
    table.add_column("exit", justify="right")
    table.add_column("ms", justify="right")
    for r in results:
        exit_style = "green" if r["exit_code"] == 0 else "red bold"
        table.add_row(r["task"], f"[{exit_style}]{r['exit_code']}[/]", f"{r['ms']}")
    console.print(table)
    console.print(f"wrote {results_path}")
    return 1 if any(r["exit_code"] != 0 for r in results) else 0


# ----------------------------------------------------------------- soak

def _soak_lane(name: str, mem_mb: int, platform: str, network: str,
               cpuset: str, label: str, deadline: float, counts: dict) -> None:
    while (now := time.time()) < deadline:
        proc = subprocess.Popen(
            [
                "docker", "run", "--rm", "--init",
                "--platform", platform,
                "--network", network,
                "--cpuset-cpus", cpuset,
                "--memory", f"{mem_mb}m",
                "--label", label,
                "-v", f"{ROOT}/tasks/{name}:/solution:ro",
                f"local/{name}", "bash", "/solution/solve.sh",
            ],
            stdout=DEVNULL, stderr=DEVNULL,
        )
        try:
            rc = proc.wait(timeout=max(deadline - now, 0.01))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            break  # deadline hit; in-flight run doesn't count either way
        if rc == 0:
            counts[name]["completed"] += 1
        elif time.time() < deadline:
            counts[name]["failed"] += 1


def cmd_soak(args: argparse.Namespace) -> int:
    platform = resolve_platform(args)
    avail = os.cpu_count() or 1
    if args.ncpu > avail:
        errcon.print(f"--ncpu {args.ncpu} exceeds available CPUs ({avail}); pick <= {avail}")
        return 1
    cpuset = f"0-{args.ncpu - 1}"

    tasks = []
    for t in load_tasks(args.only):
        have_image = subprocess.run(
            ["docker", "image", "inspect", f"local/{t['name']}"],
            stdout=DEVNULL, stderr=DEVNULL,
        ).returncode == 0
        if have_image:
            tasks.append(t)
        else:
            errcon.print(f"skip {t['name']} (no local image)")
    if not tasks:
        errcon.print("no runnable tasks (build images first)")
        return 1

    soak_dir = ROOT / "soak_logs"
    soak_dir.mkdir(exist_ok=True)
    for old in soak_dir.glob("*.tsv"):
        old.unlink()
    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)

    start = int(time.time())
    deadline = start + args.duration
    label = f"soak_session={start}"
    errcon.print(
        f"soak: ncpu={args.ncpu} (cpuset {cpuset})  duration={args.duration}s  "
        f"platform {platform}  {len(tasks)} lanes"
    )

    counts = {t["name"]: {"completed": 0, "failed": 0} for t in tasks}
    threads = [
        threading.Thread(
            target=_soak_lane,
            args=(t["name"], t["memory_mb"], platform, args.network, cpuset, label, deadline, counts),
            daemon=True,
        )
        for t in tasks
    ]

    progress = Progress(
        TextColumn("[bold]soak"),
        BarColumn(bar_width=None),
        TextColumn("{task.completed:>4.0f}/{task.total:.0f}s"),
        console=console,
    )
    bar = progress.add_task("soak", total=args.duration)

    def counts_table() -> Table:
        names = sorted(counts)
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
                    c = counts[n]
                    fail = f"[red]{c['failed']}[/]" if c["failed"] else "[dim]0[/]"
                    cells += [n, f"[green]{c['completed']}[/]", fail]
                else:
                    cells += ["", "", ""]
            table.add_row(*cells)
        return table

    def render() -> Group:
        progress.update(bar, completed=min(time.time() - start, args.duration))
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
        # kill anything from this session still running (in-flight at the deadline)
        leftover = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"label={label}"],
            capture_output=True, text=True,
        ).stdout.split()
        if leftover:
            subprocess.run(["docker", "kill", *leftover], stdout=DEVNULL, stderr=DEVNULL)

    elapsed = int(time.time()) - start

    lines = []
    for name in sorted(counts):
        c = counts[name]
        line = f"{name}\t{c['completed']}\t{c['failed']}"
        (soak_dir / f"{name}.tsv").write_text(line + "\n")
        lines.append(line)
    (soak_dir / "all.tsv").write_text("\n".join(lines) + "\n" if lines else "")

    per_task = [{"task": n, **counts[n]} for n in counts]
    per_task.sort(key=lambda r: -r["completed"])
    summary = {
        "ncpus": args.ncpu,
        "seconds": elapsed,
        "total_completed": sum(r["completed"] for r in per_task),
        "total_failed": sum(r["failed"] for r in per_task),
        "tasks": per_task,
    }
    results_path.write_text(json.dumps(summary, indent=2) + "\n")

    console.print(
        f"ncpu={summary['ncpus']}  elapsed={summary['seconds']}s  "
        f"total_completed=[green]{summary['total_completed']}[/]  "
        f"total_failed=[red]{summary['total_failed']}[/]"
    )
    console.print(f"wrote {results_path}")
    return 0


# ----------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--platform", default=None,
                       help="docker --platform (default: $PLATFORM or native)")
        p.add_argument("--only", nargs="*", default=os.environ.get("ONLY", "").split() or None,
                       help="restrict to these task names")

    p_build = sub.add_parser("build", help="build all task images in parallel")
    common(p_build)
    p_build.set_defaults(fn=cmd_build)

    p_bench = sub.add_parser("benchmark", help="run oracle solutions serially, record latency")
    common(p_bench)
    p_bench.add_argument("--network", default=os.environ.get("NETWORK", "none"))
    p_bench.add_argument("--results", default=os.environ.get("RESULTS", "results/benchmark.json"))
    p_bench.set_defaults(fn=cmd_benchmark)

    p_soak = sub.add_parser("soak", help="one lane per task, cycle runs until the deadline")
    common(p_soak)
    p_soak.add_argument("--network", default=os.environ.get("NETWORK", "none"))
    p_soak.add_argument("--ncpu", type=int, default=int(os.environ.get("NCPUS", 4)))
    p_soak.add_argument("--duration", type=int, default=int(os.environ.get("DURATION", 20)),
                        help="seconds to run")
    p_soak.add_argument("--results", default=os.environ.get("SOAK_RESULTS", "results/soak.json"))
    p_soak.set_defaults(fn=cmd_soak)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
