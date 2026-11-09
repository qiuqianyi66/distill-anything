#!/usr/bin/env python3
"""把已有产物里的「路径:行」锚点抽成 evidence.jsonl（一次性迁移，只读产物不改正文）。

用法：python scripts/migrate_legacy.py --project out/distill-<slug>
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate as gate_mod


def locate(art, anchor):
    """返回 (文件, 行段) 或 (None, 原因)。歧义即拒绝，不猜。"""
    path_part, line = anchor.rsplit(":", 1)
    rng = gate_mod.parse_lines(line)
    if not rng:
        return None, "行号非法"
    valid, longest = [], 0
    for b in gate_mod.anchor_bases(art):
        p = b / path_part.replace("\\", "/")
        if not p.is_file():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        longest = max(longest, len(lines))
        if rng[1] <= len(lines):
            valid.append((p, rng, gate_mod.fingerprint(lines[rng[0] - 1:rng[1]])))
    if not valid:
        return None, f"行号越界（最长 {longest} 行）" if longest else "文件不存在"
    if len({fp for _, _, fp in valid}) > 1:
        return None, f"{len(valid)} 个同名文件内容不同，需写全相对路径"
    p, rng, _ = valid[0]
    return (p, rng), ""


def clean(line):
    """把产物行压成一条可读断言：去列表符、反引号、锚点、标记、URL、表格分隔与尾部残留。

    表格行（判据表 / 证据台账）整行进 statement 会带出「|」和序号，读起来是机械残渣；
    这里按单元格合并，并丢掉纯数字首列。
    """
    s = re.sub(r"^[-*]\s+", "", line.strip()).replace("`", "")
    s = gate_mod.ANCHOR_FILE_RE.sub("", s)
    s = gate_mod.MARK_RE.sub("", s)
    s = re.sub(r"\s*\[(?:O|D|I)\]", "", s)
    s = re.sub(r"https?://[^\s)\]|]+", "", s)
    if "|" in s:
        cells = [c.strip() for c in s.strip("|").split("|")]
        cells = [c for c in cells if c and not re.fullmatch(r"[0-9]+|[ODI]", c)]
        s = " / ".join(cells)
    s = re.sub(r"\s+", " ", s)
    # 只删「… | 证据」这种表格残留；「自述不构成证据」这类句子成分保留
    s = re.sub(r"[\s，。:：|、/]+证据[:：]?\s*$", "", s)
    return s.strip(" ，。:：|/")[:120]


def main():
    ap = argparse.ArgumentParser(description="legacy anchor migration")
    ap.add_argument("--project", required=True, help="out/distill-<slug>")
    ap.add_argument("--observed-at", default="")
    ap.add_argument("--source", default="shallow:无commit", help="写入 source_ref；文档类可用 file:sha256:<前8位>")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    proj = Path(args.project)
    if not proj.is_dir():
        print(f"目录不存在：{proj}", file=sys.stderr)
        return 4
    today = args.observed_at or __import__("datetime").date.today().isoformat()
    entries, skipped = {}, []

    for art in sorted(proj.rglob("*.md")):
        rel0 = art.relative_to(proj).as_posix()
        if rel0.startswith(("raw/", "notes/")) or ".bak" in art.name:
            continue
        try:
            text = art.read_text(encoding="utf-8")
        except OSError as exc:
            skipped.append(f"{rel0} 读不了：{exc}")
            continue
        for ln in text.splitlines():
            for anc in gate_mod.ANCHOR_FILE_RE.findall(ln):
                hit, why = locate(art, anc)
                if not hit:
                    skipped.append(f"{rel0} -> {anc}（{why}）")
                    continue
                p, rng = hit
                try:
                    rel = p.resolve().relative_to(proj.resolve()).as_posix()
                except ValueError:
                    skipped.append(f"{rel0} -> {anc}（目标在项目外，产物不自包含）")
                    continue
                mk = gate_mod.MARK_RE.search(ln)
                lv = mk.group(1) if mk else "O"
                spec = str(rng[0]) if rng[0] == rng[1] else f"{rng[0]}-{rng[1]}"
                key = f"{rel}|{spec}|{lv}"
                if key in entries:
                    if rel0 not in entries[key]["supports"]:
                        entries[key]["supports"].append(rel0)
                    continue
                seg = p.read_text(encoding="utf-8", errors="replace").splitlines()[rng[0] - 1:rng[1]]
                entries[key] = {
                    "id": "E-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8],
                    "path": rel,
                    "lines": spec,
                    "level": lv,
                    "statement": clean(ln),
                    "quote_sha1": gate_mod.fingerprint(seg),
                    "observed_at": today,
                    "source_ref": args.source,
                    "supports": [rel0],
                }

    rows = list(entries.values())
    out = proj / "evidence.jsonl"
    print(f"条目 {len(rows)} 条" + ("（dry-run 未写）" if args.dry_run else f" -> {out}"))
    if not args.dry_run:
        out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    if skipped:
        print(f"跳过 {len(skipped)} 处：")
        for s in skipped[:12]:
            print("  " + s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
