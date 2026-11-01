"""Round 4 #2: Ollama CPU/RSS sampling from /proc, and its path into the cost.

Builds a fake /proc tree under tmp_path with a process whose comm is 'ollama' and
whose stat/status report known CPU ticks and RSS, then asserts procstat reads them
and that the cost table attributes non-zero Ollama CPU seconds.
"""

from __future__ import annotations

import os

from eval import procstat
from docs import generate_tables as gt


def _write_fake_proc(root: str, pid: int, comm: str, utime: int, stime: int, hwm_kb: int):
    d = os.path.join(root, str(pid))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "comm"), "w", encoding="utf-8") as f:
        f.write(comm + "\n")
    # /proc/<pid>/stat: fields 14 (utime) and 15 (stime) are indices 13,14.
    fields = ["0"] * 52
    fields[0] = str(pid)
    fields[1] = f"({comm})"
    fields[2] = "S"
    fields[13] = str(utime)
    fields[14] = str(stime)
    with open(os.path.join(d, "stat"), "w", encoding="utf-8") as f:
        f.write(" ".join(fields) + "\n")
    with open(os.path.join(d, "status"), "w", encoding="utf-8") as f:
        f.write(f"Name:\t{comm}\nVmHWM:\t{hwm_kb} kB\n")


def test_sample_ollama_reads_fake_proc(tmp_path):
    _write_fake_proc(str(tmp_path), 4242, "ollama", utime=300, stime=100, hwm_kb=2_097_152)
    _write_fake_proc(str(tmp_path), 7, "python3", utime=50, stime=50, hwm_kb=100_000)
    s = procstat.sample_ollama(name="ollama", proc_dir=str(tmp_path), clk_tck=100)
    # (300 + 100) ticks / 100 = 4.0 CPU seconds; 2 GiB RSS = 2048 MB.
    assert s["cpu_seconds"] == 4.0
    assert s["peak_rss_mb"] == 2048.0
    assert s["pids"] == [4242]


def test_sample_ollama_absent_is_zero(tmp_path):
    s = procstat.sample_ollama(name="ollama", proc_dir=str(tmp_path), clk_tck=100)
    assert s["cpu_seconds"] == 0.0
    assert s["peak_rss_mb"] == 0.0


def test_cost_table_includes_ollama_cpu():
    # A measured System C block with an Ollama CPU figure must surface in the cost.
    data = {
        "systems": {
            "A_v1_regex": {"status": "pending real run"},
            "B_embeddings_only": {"status": "pending real run"},
            "C_embeddings_slm": {
                "status": "measured",
                "cost": {
                    "cpu_seconds_per_item": 0.1600,
                    "harness_cpu_seconds_per_item": 0.0100,
                    "ollama_cpu_seconds_per_item": 0.1500,
                    "harness_peak_rss_mb": 400.0,
                    "ollama_peak_rss_mb": 2048.0,
                    "items_scored": 100,
                },
            },
            "D_embeddings_lr": {"status": "pending real run"},
            "E_lr_then_slm": {"status": "pending real run"},
        },
    }
    table = gt._cost_table(data)
    assert "Ollama CPU s/item" in table
    assert "0.15" in table          # the Ollama CPU figure
    assert "2048.0" in table        # the Ollama RSS, reported separately
    assert "us-east-1" in table     # region stated in the price assumption
    assert "ASSUMPTION" in table
