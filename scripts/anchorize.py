#!/usr/bin/env python3
"""把产物正文里的路径锚点收口成证据 id（T4/T7 用）。

规则：
- 只处理**行内含 [O]/[D]/[I] 标记**的行（含证据台账表格行）。没标记的行里的路径是「指路」，不是证据，保留。
- 同一处 (path, lines, level) 已有条目则复用 id；没有则用与 evidence add 完全相同的公式补一条。
- 解析不到路径的锚点原样保留并计数，不猜。

用法：
    python anchorize.py --dir out/distill-x [--date 2026-11-08] [--source <ref>] [--dry-run]
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate as gate_mod


def read_rows(path):
    if not path.exists():
        return []
    rows = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            rows.append({"__bad__": ln})
    return rows


def write_rows(path, rows):
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def artifacts_of(ddir):
    out = []
    for p in Path(ddir).rglob("*.md"):
        if any(part in ("raw", "notes") for part in p.parts):
            continue
        if ".bak" in p.name:
            continue
        out.append(p)
    return out


def stmt_of(line):
    s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)
    s = gate_mod.ANCHOR_FILE_RE.sub("", s)
    s = gate_mod.ANCHOR_URL_RE.sub("", s)
    s = gate_mod.MARK_RE.sub("", s)
    s = s.replace("|", " ")
    return re.sub(r"\s+", " ", s).strip(" ，。:：/")[:120]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="out/distill-<slug>")
    ap.add_argument("--date", default="2026-11-08")
    ap.add_argument("--source", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ddir = Path(args.dir)
    if not ddir.is_dir():
        print(f"目录不存在：{ddir}", file=sys.stderr)
        return 4
    ev_path = ddir / "evidence.jsonl"
    rows = read_rows(ev_path)
    by_key = {(r.get("path"), str(r.get("lines"))): r.get("id") for r in rows if r.get("id")}
    known_ids = {r.get("id") for r in rows if r.get("id")}

    source = args.source
    if not source:
        refs = [r.get("source_ref") for r in rows if r.get("source_ref")]
        source = max(set(refs), key=refs.count) if refs else "（待填：commit 或抓取日期）"

    added, kept, replaced = [], [], 0

    for art in artifacts_of(ddir):
        lines = art.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        for ln in lines:
            mark = gate_mod.MARK_RE.search(ln)
            if not mark:
                out.append(ln)
                continue

            def _sub(m, _ln=ln, _lvl=mark.group(1)):
                a = m.group(0)
                p = gate_mod.resolve_anchor_path(art, a)
                if p is None:
                    kept.append(f"{art.name}: {a}")
                    return a
                try:
                    rel = p.resolve().relative_to(ddir.resolve()).as_posix()
                except ValueError:
                    kept.append(f"{art.name}: {a}（不在目录内）")
                    return a
                line_part = a.rsplit(":", 1)[1]
                key = (rel, line_part)
                if key in by_key:
                    return by_key[key]
                eid = "E-" + hashlib.sha1(f"{rel}|{line_part}|{_lvl}".encode("utf-8")).hexdigest()[:8]
                if eid in known_ids:
                    by_key[key] = eid
                    return eid
                rows.append({
                    "id": eid,
                    "path": rel,
                    "lines": line_part,
                    "level": _lvl,
                    "statement": stmt_of(_ln),
                    "quote_sha1": gate_mod.fingerprint(
                        p.read_text(encoding="utf-8", errors="replace").splitlines()[
                            int(line_part.split("-")[0]) - 1: int(line_part.split("-")[-1])
                        ]
                    ),
                    "observed_at": args.date,
                    "source_ref": source,
                    "supports": [],
                })
                known_ids.add(eid)
                by_key[key] = eid
                added.append(eid)
                return eid

            new = gate_mod.ANCHOR_FILE_RE.sub(_sub, ln)
            if new != ln:
                replaced += new.count("E-") - ln.count("E-")
            out.append(new)
        if not args.dry_run:
            art.write_text("\n".join(out) + "\n", encoding="utf-8")

    if not args.dry_run and added:
        write_rows(ev_path, rows)

    print(f"替换锚点 {replaced} 处 / 新增证据 {len(added)} 条 / 未解析保留 {len(kept)} 处")
    for k in kept[:6]:
        print("  保留：", k)
    if args.dry_run:
        print("（dry-run：未写文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
