#!/usr/bin/env python3
"""判据牙齿审计：哪些 check 从没被反例打红过（= 没有牙齿）。

用法：python scripts/teeth_audit.py [gate.py] [技能根]
默认拿本脚本同级目录定位 gate.py 与 tests/fixtures。只读，不改任何文件。

输出每条判据的 True/False/None 分布与「从未判红」清单。
注意：只统计 tests/fixtures 静态样例；main() 里的动态用例（links / strict-anchor /
write-integrity）不在此列，看到它们「没牙齿」时先回 tests/run_gate_tests.py 核对。
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "gate.py"
ROOT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE.parent

seen = {}


def feed(target):
    proc = subprocess.run([sys.executable, str(GATE), str(target), "--json"],
                          capture_output=True, text=True, encoding="utf-8")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return
    for c in data.get("checks", []):
        row = seen.setdefault(c["name"], {"true": 0, "false": 0, "none": 0, "where_false": []})
        if c.get("ok") is True:
            row["true"] += 1
        elif c.get("ok") is False:
            row["false"] += 1
            row["where_false"].append(str(target.name))
        else:
            row["none"] += 1


for p in sorted((ROOT / "tests" / "fixtures").glob("*.md")):
    feed(p)
for d in sorted((ROOT / "tests" / "fixtures").iterdir()):
    if d.is_dir() and (d / "report.md").exists():
        feed(d / "report.md")

print("== 反例覆盖 ==")
print(f"{'判据':<22} {'True':>5} {'False':>6} {'None':>5}  反向用例")
for name, row in sorted(seen.items()):
    neg = ", ".join(sorted(set(row["where_false"]))[:4]) or "—"
    print(f"{name:<22} {row['true']:>5} {row['false']:>6} {row['none']:>5}  {neg}")

print("\n== 从未被判红过的判据（fixture 层面没有反例）==")
for name, row in sorted(seen.items()):
    if row["false"] == 0:
        print(f"  {name}  (True={row['true']}, None={row['none']})")
