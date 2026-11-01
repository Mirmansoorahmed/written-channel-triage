"""Read CPU time and RSS of the Ollama server/runner processes (Round 4 #2).

The SLM cost does not show up in the harness process -- it is spent inside the
Ollama server (and its model runner subprocess). To get an honest cost per 1,000
messages we must add the Ollama CPU seconds consumed during a system's pass. This
reads them straight from /proc so there is no psutil dependency, and the reader is
injected so a test can supply fake /proc contents.

Linux /proc/<pid>/stat fields (1-indexed): 14 utime, 15 stime (clock ticks);
/proc/<pid>/status VmHWM is the peak RSS. CPU seconds = (utime + stime) / CLK_TCK.
"""

from __future__ import annotations

import os

CLK_TCK = 100  # os.sysconf('SC_CLK_TCK') is 100 on Linux; overridable in tests.


def _default_pids_by_name(name: str) -> list[int]:
    """PIDs whose /proc/<pid>/comm or cmdline contains `name` (e.g. 'ollama')."""
    pids: list[int] = []
    proc = "/proc"
    if not os.path.isdir(proc):
        return pids
    for entry in os.listdir(proc):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"{proc}/{pid}/comm", encoding="utf-8") as f:
                comm = f.read().strip()
            hit = name in comm
            if not hit:
                with open(f"{proc}/{pid}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "replace")
                hit = name in cmd
            if hit:
                pids.append(pid)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return pids


def _read_cpu_seconds(pid: int, proc_dir: str, clk_tck: int) -> float:
    with open(f"{proc_dir}/{pid}/stat", encoding="utf-8") as f:
        fields = f.read().split()
    # Field 14 = utime, 15 = stime (1-indexed) -> indices 13, 14.
    utime, stime = int(fields[13]), int(fields[14])
    return (utime + stime) / clk_tck


def _read_rss_hwm_kb(pid: int, proc_dir: str) -> int:
    with open(f"{proc_dir}/{pid}/status", encoding="utf-8") as f:
        for line in f:
            if line.startswith("VmHWM:"):
                return int(line.split()[1])  # kB
    return 0


def sample_ollama(name: str = "ollama", proc_dir: str = "/proc",
                  clk_tck: int = CLK_TCK, pids: list[int] | None = None) -> dict:
    """Return {'cpu_seconds': float, 'peak_rss_mb': float, 'pids': [...]}.

    `pids` can be supplied directly (tests); otherwise they are discovered by name.
    A zero/empty reading (Ollama not running, non-Linux) is returned rather than
    raising, so the harness degrades to harness-only cost.
    """
    if pids is None:
        pids = _default_pids_by_name(name) if proc_dir == "/proc" else _scan_fake(proc_dir, name)
    cpu = 0.0
    rss_kb = 0
    seen: list[int] = []
    for pid in pids:
        try:
            cpu += _read_cpu_seconds(pid, proc_dir, clk_tck)
            rss_kb += _read_rss_hwm_kb(pid, proc_dir)
            seen.append(pid)
        except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
            continue
    return {"cpu_seconds": round(cpu, 4), "peak_rss_mb": round(rss_kb / 1024, 1), "pids": seen}


def _scan_fake(proc_dir: str, name: str) -> list[int]:
    """Discover PIDs under a fake /proc (for tests): numeric dirs whose comm matches."""
    pids = []
    if not os.path.isdir(proc_dir):
        return pids
    for entry in os.listdir(proc_dir):
        if not entry.isdigit():
            continue
        comm_path = os.path.join(proc_dir, entry, "comm")
        try:
            with open(comm_path, encoding="utf-8") as f:
                if name in f.read():
                    pids.append(int(entry))
        except FileNotFoundError:
            continue
    return pids
