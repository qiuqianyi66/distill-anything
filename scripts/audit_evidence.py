#!/usr/bin/env python3
"""体检一个或多个产物容器：具体性密度 / raw 材料进证据率 / 上游原文漂移。

只输出观察，不给判定——判定仍由 gate 做。三块可以分开看：
  密度   结论行有没有具体数字、原话、E id、路径行号、日期（判断是不是空话）
  覆盖   raw 里的实质材料有多少进了 evidence.jsonl（判断有没有读了不写）
  漂移   raw 原文与上游现在的内容是否一致（需要 --remote，且本机有 gh）

用法：
  python scripts/audit_evidence.py <产物目录或容器父目录> [--remote]
  python scripts/audit_evidence.py out/skills-governance --remote
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

MARK = re.compile(r"\[(O|D|I)\]")
CONCRETE = re.compile(
    r"(\d+(\.\d+)?\s*(%|行|条|个|次|ms|s|KB|分|倍)|「[^」]+」|\"[^\"]+\""
    r"|E-[0-9a-f]{8}|[\w\-/.]+\.[\w]+:\d+|\d{4}-\d{2}-\d{2})"
)
REPO_RE = re.compile(r"github\.com/([\w\-.]+)/([\w\-.]+)@")
MATERIAL = {".md", ".txt", ".ts", ".py", ".json", ".csv", ".jsonl", ".toml", ".yml", ".yaml"}


def body_of(path):
    txt = path.read_text(encoding="utf-8", errors="replace")
    if txt.startswith("---"):
        end = txt.find("\n---", 3)
        return txt[end + 4:] if end > 0 else txt
    return txt


def containers(root):
    if root.is_file():
        return [root.parent]
    # 与 gate 的 iter_containers 同口径：跳过 raw/ 与 notes/ 下的快照副本，
    # 否则被蒸馏对象里自带的 distill-* 目录会被当成我们的产物。
    out = sorted(p for p in root.rglob("distill-*")
                 if p.is_dir() and not any(part in ("raw", "notes") for part in p.parts))
    return out or [root]


def product_of(container):
    for name in ("report.md", "SKILL.md"):
        p = container / name
        if p.exists():
            return p
    return None


def density(container):
    """结论行里带具体细节的比例。低于五成且结论数够多，通常是通篇判断没有事实。"""
    p = product_of(container)
    if not p:
        return None
    lines = [ln.strip() for ln in body_of(p).splitlines() if MARK.search(ln)]
    if not lines:
        return (0, 0, 0.0)
    concrete = [ln for ln in lines if CONCRETE.search(ln)]
    return (len(lines), len(concrete), len(concrete) / len(lines))


def cited_paths(container):
    ev = container / "evidence.jsonl"
    if not ev.exists():
        return set()
    got = set()
    for line in ev.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = (rec.get("path") or "").replace("\\", "/")
        if p:
            got.add(p)
    return got


def coverage(container):
    """raw 里实质材料进了证据库的比例。整仓克隆（材料过多）不算，避免噪声淹没结论。"""
    raw = container / "raw"
    if not raw.exists():
        return None
    material = [f for f in raw.rglob("*")
                if f.is_file() and f.suffix.lower() in MATERIAL
                and f.name != ".gitkeep" and f.stat().st_size > 200]
    if not material or len(material) > 120:
        return None
    cited = cited_paths(container)
    hit = [f for f in material if f.relative_to(container).as_posix() in cited]
    miss = [f.name for f in material if f.relative_to(container).as_posix() not in cited]
    return (len(material), len(hit), miss[:3])


def upstream_repo(container):
    p = product_of(container)
    if not p:
        return None
    head = p.read_text(encoding="utf-8", errors="replace")[:600]
    m = REPO_RE.search(head)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def upstream_raw(repo, name):
    """按候选名取上游原文；API 大小写敏感，本地存成小写时要试大写。"""
    low = name.lower()
    variants = {"readme.md": ["README.md", "readme.md"],
                "agents.md": ["AGENTS.md", "agents.md"],
                "claude.md": ["CLAUDE.md", "claude.md"]}.get(low, [name, name.upper()])
    for v in variants:
        r = subprocess.run(["gh", "api", f"repos/{repo}/contents/{v}",
                            "-H", "Accept: application/vnd.github.raw"],
                           capture_output=True, timeout=90)
        if r.returncode == 0 and r.stdout:
            return r.stdout
    return None


def normalize(blob):
    """归一化后再比，避免行尾与 BOM 造成的假漂移。"""
    text = blob.decode("utf-8", errors="replace").lstrip("\ufeff")
    return "\n".join(ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def drift(container):
    repo = upstream_repo(container)
    if not repo:
        return None
    raw = container / "raw"
    if not raw.exists():
        return None
    files = [f for f in raw.rglob("*") if f.is_file() and f.suffix.lower() == ".md"
             and f.name != ".gitkeep" and f.stat().st_size > 200]
    result = {"repo": repo, "same": 0, "changed": [], "miss": []}
    for f in files[:6]:
        up = upstream_raw(repo, f.name)
        if up is None:
            result["miss"].append(f.name)
            continue
        if normalize(up) == normalize(f.read_bytes()):
            result["same"] += 1
        else:
            result["changed"].append(f.name)
    return result


def main():
    ap = argparse.ArgumentParser(description="产物证据体检（只报观察，不下判定）")
    ap.add_argument("target", help="产物文件、容器目录或容器父目录")
    ap.add_argument("--remote", action="store_true", help="核对上游原文是否已变（需要 gh 且联网）")
    args = ap.parse_args()

    root = Path(args.target)
    if not root.exists():
        print(f"路径不存在：{root}", file=sys.stderr)
        return 4

    print("== 具体性密度（结论行）==")
    print(f"{'容器':34}{'结论':>5}{'具体':>5}{'密度':>7}")
    thin = []
    for c in containers(root):
        d = density(c)
        if d is None:
            continue
        total, concrete, ratio = d
        print(f"{c.name:34}{total:>5}{concrete:>5}{ratio:>7.0%}")
        if ratio < 0.5 and total >= 10:
            thin.append(c.name)
    if thin:
        print("  低密度（<50% 且结论≥10 条）：" + "、".join(thin))

    print("\n== raw 材料进证据率 ==")
    print(f"{'容器':34}{'材料':>5}{'进库':>5}{'覆盖':>7}  未进库（样本）")
    for c in containers(root):
        v = coverage(c)
        if v is None:
            continue
        total, hit, miss = v
        sample = "、".join(miss) if miss else "—"
        print(f"{c.name:34}{total:>5}{hit:>5}{hit / total:>7.0%}  {sample}")

    if args.remote:
        print("\n== 上游原文漂移（归一化比对）==")
        print(f"{'容器':34}{'仓库':34}{'一致':>5}  变动文件")
        for c in containers(root):
            r = drift(c)
            if r is None:
                continue
            changed = "、".join(r["changed"]) if r["changed"] else "—"
            miss = f"  (取不到：{'、'.join(r['miss'])})" if r["miss"] else ""
            print(f"{c.name:34}{r['repo']:34}{r['same']:>5}  {changed}{miss}")

    print("\n说明：以上仅为观察。是否达标仍以 gate 结论为准；漂移只说明原文变了，不等同于产物断言已错。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
