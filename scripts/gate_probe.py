#!/usr/bin/env python3
"""内容掏空探针：判断门禁的每条检查是「验工作」还是「验排版」。

来源：ronce-racine docs/evaluating-skills.md 的 `npm run eval:probe`
（原始动机：一个只有 15 行代码的 fixture 上，门只能 key 在交付物的措辞上，
于是每条门都退化成格式门，任何带着该格式的文本都能通过）。

做法：把产物按结构保留、内容掏空（标题留着、表格只剩表头、正文全换成占位、
标记与锚点全部去掉），再用同一套 gate 判它。探针通过的检查 = 格式门；
只有原产物能过、探针过不了的 = 真在验内容的检查。

    python scripts/gate_probe.py <产物或目录> [--recursive] [--json]
    python scripts/gate_probe.py --root out --recursive --json

退出码：0 探完（不代表好坏）/ 1 读不到文件 / 2 没有可用产物。
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate as gate_mod

ANCHOR_RE = gate_mod.ANCHOR_FILE_RE
MARK_RE = gate_mod.MARK_RE
URL_RE = re.compile(r"https?://[^\s)\]|]+")
PLACEHOLDER = ""  # 真·零内容：不放占位词，否则「非空」类检查会把占位词当成内容


def skeleton(txt):
    """保留结构（frontmatter/标题/表格骨架），掏空一切内容与证据。"""
    lines = txt.splitlines()
    out = []
    in_front = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if i == 0 and s == "---":
            in_front = True
            out.append(ln)
            continue
        if in_front:
            out.append(ln)
            if s == "---":
                in_front = False
            continue
        if s.startswith("#"):
            out.append(ln)
            continue
        if s.startswith("|"):
            # 表头与分隔行保留，数据行只留竖线骨架
            if set(s) <= set("|-: "):
                out.append(ln)
            elif not out or not out[-1].lstrip().startswith("|"):
                out.append(ln)
            else:
                cells = [c for c in s.strip("|").split("|")]
                out.append("|" + "|".join(PLACEHOLDER for _ in cells) + "|")
            continue
        if s.startswith("- ") or re.match(r"^\d+\.\s", s) or s.startswith("* "):
            out.append("-")
            continue
        if s == "":
            out.append("")
            continue
        out.append(PLACEHOLDER)
    return "\n".join(out) + "\n"


def probe_one(target: Path):
    txt = target.read_text(encoding="utf-8", errors="replace")
    base = gate_mod.check(target)
    sk = skeleton(txt)
    # 探针文件放在同目录临时文件，保证任何残留的相对路径语义不变
    with tempfile.NamedTemporaryFile("w", suffix=".probe.md", dir=str(target.parent),
                                     delete=False, encoding="utf-8") as fh:
        fh.write(sk)
        probe_path = Path(fh.name)
    try:
        pr = gate_mod.check(probe_path)
    finally:
        probe_path.unlink(missing_ok=True)
    prod_pass = {c["name"] for c in base["checks"] if c["ok"] is True}
    probe_pass = {c["name"] for c in pr["checks"] if c["ok"] is True}
    return {
        "target": str(target),
        "product_status": base["status"],
        "probe_status": pr["status"],
        "product_pass": sorted(prod_pass),
        "format_gates": sorted(prod_pass & probe_pass),
        "content_checks": sorted(prod_pass - probe_pass),
        "probe_extra": sorted(probe_pass - prod_pass),
    }


def collect(paths, recursive):
    arts = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            arts.append(p)
        elif p.is_dir():
            if recursive:
                # 只认 distill-* 容器根级 md，与 distill.py 的 artifacts_of 口径一致；
                # 否则 README、第三方技能、历史脚本都会被当产物打分（P1 基线踩过）
                arts += [q for q in p.rglob("*.md")
                         if q.parent.name.startswith("distill-")
                         and not any(part in ("raw", "notes") for part in q.parts)
                         and ".bak" not in q.name and ".probe" not in q.name]
            else:
                arts += [q for q in p.glob("distill-*/*.md") if ".bak" not in q.name]
    return sorted(set(arts))


def main():
    ap = argparse.ArgumentParser(prog="gate_probe")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--root", default="")
    ap.add_argument("--recursive", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    targets = list(args.paths) + ([args.root] if args.root else [])
    if not targets:
        print("至少给一个产物路径或 --root", file=sys.stderr)
        return 2
    arts = collect(targets, args.recursive)
    if not arts:
        print("没找到产物", file=sys.stderr)
        return 2
    rows = []
    for a in arts:
        try:
            rows.append(probe_one(a))
        except OSError as exc:
            print(f"读不了 {a}: {exc}", file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"[{r['product_status']}→{r['probe_status']}] {r['target']}")
            print(f"   格式门 {len(r['format_gates'])}: {', '.join(r['format_gates']) or '—'}")
            print(f"   验内容 {len(r['content_checks'])}: {', '.join(r['content_checks']) or '—'}")
    if args.json:  # --json 时不能追加人类可读行，否则 stdout 不是合法 JSON
        return 0
    all_fmt = sum(len(r["format_gates"]) for r in rows)
    all_content = sum(len(r["content_checks"]) for r in rows)
    print(f"\n合计：格式门 {all_fmt} 条 / 验内容 {all_content} 条"
          f"（格式占比 {all_fmt / (all_fmt + all_content) * 100:.0f}%）" if all_fmt + all_content else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
