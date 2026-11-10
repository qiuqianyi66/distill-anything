#!/usr/bin/env python3
"""distill-anything 执行层：只做机械动作，不承载任何判据。

子命令：
    init <slug> --type mechanism|perspective|rules   生成产物骨架
    gate <path...>                                    复用 gate.py 校验，多文件汇总
    index [--root out]                                校验证据库，标 stale/dead，回填 supports
    evidence add ...                                  读原文算指纹，追加一条证据

退出码：0 ok / 1 有硬问题 / 2 只有可续期问题 / 3 已存在不覆盖 / 4 参数非法
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate as gate_mod

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
EID_RE = re.compile(r"E-[0-9a-f]{8}")
ANCHOR_RE = re.compile(
    r"[A-Za-z0-9_\-./\\]+\.(?:md|ts|tsx|js|jsx|mjs|cjs|py|json|go|java|kt|rs|ps1|sh|yaml|yml|toml|sql|txt|csv|html):\d+(?:-\d+)?"
)
TYPE_DIR = {"mechanism": "mechanism", "perspective": "perspective", "rules": "rules", "refuse": "refuse"}

SKELETON_MECHANISM = """---
name: {slug}
description: 一句话说清这份产物解决什么问题、什么情况下该用它。
source: {src}
---

# {slug}

## 1 结构地图
（待填：对象由哪几块构成、入口在哪、边界在哪）

## 2 关键决策与代价
（待填：每个决策换取了什么、付出了什么）

## 3 可搬机制 / 核心框架

（待填：每条挂一层标记（O 观察 / D 合成 / I 推断）+ E-xxxx 锚点，锚点用 distill evidence add 生成的 id）

## 4 明确不搬
（待填：不搬什么、为什么、什么情况下才值得搬）

## 5 证据台账
| 断言 | 层级 | 锚点 |
|---|---|---|
| （待填） |  |  |

## 6 诚实边界
- （待填：这份产物做不到什么、只读到哪一层）

## 7 未知台账
| 未知 | 为什么解不了 | 需要什么才能解 |
|---|---|---|
| （待填） |  |  |
"""

SKELETON_PERSPECTIVE = """---
name: {slug}
description: 一句话说清这份产物捕捉了谁的什么思维方式、什么情况下该用它。
source: {src}
---

# {slug}

## 1 心智模型（3-7 个，宁少勿多）
（待填：每个模型写清解决什么问题、什么情况下触发、什么情况下不成立）

## 2 决策启发式
（待填：面对新问题时先看什么、后看什么、放弃什么）

## 3 表达 DNA
（待填：惯用词、句式、拒绝回答的问题）

## 4 内在张力（至少 1 对不调和的矛盾）
（待填：两条互相冲突的信念，各自成立的条件）

## 5 明确不做
（待填：这个对象绝对不会做的事）

## 6 证据台账
| 断言 | 层级 | 锚点 |
|---|---|---|
| （待填） |  |  |

## 7 诚实边界
- （待填：做不到什么、语料截止到哪）

## 8 未知台账
| 未知 | 为什么解不了 | 需要什么才能解 |
|---|---|---|
| （待填） |  |  |
"""

SKELETON_RULES = """---
name: {slug}
description: 一句话说清这份产物从几次失败里抽出了哪几条判据、覆盖什么场景。
source: {src}
---

# {slug}

## 1 判据表

| # | 触发条件（何时适用） | 禁止行为 | 一线修复 | 仍失败兜底 | 证据 |
|---|---|---|---|---|---|
| 1 | （待填） | （待填） | （待填） | （待填） |  |

## 2 假阳性排除（哪些情况不算违规）
- （待填：看起来像违规，实际是什么原因，判据为何不适用）

## 3 根因层（表象 vs 机制）
- 表象：
- 机制：

## 4 防复发门禁
- 检查项：
- 反例验证：（把 X 故意改坏，检查必须变红，附实测结果）
- 静默失效点：

## 6 内在张力（不要调和）
- （待填：A 与 B 的冲突，在什么场景选 A、什么场景选 B）

## 7 它绝对不做什么
- （待填：对象明确拒绝的做法）

## 8 证据台账
| 结论 | 层级 | 锚点 |
|---|---|---|
| （待填） |  |  |

## 9 诚实边界
- （待填：只覆盖什么场景、样本量多少、未验证部分）

## 10 未知台账
| 未知 | 为什么解不了 | 需要什么才能解 |
|---|---|---|
| （待填） |  |  |
"""

SKELETON_REFUSE = """---
name: {slug}
description: 判定 <对象> 不值得蒸馏，并说明凭什么这么判。
decision: refuse
source: {src}
---

# {slug}：不蒸

## 判断
（待填：不蒸 / 只蒸某一层 / 先补材料再蒸）

## 理由（至少 3 条，每条要能判真假）
- （待填：从对象自身读到的证据 + 锚点，说明为什么撑不起一份产物）

## 未知台账

| 未知 | 为什么解不了 | 需要什么才能解 |
|---|---|---|
| （待填：要蒸它还缺什么） |  |  |
"""

SKELETONS = {
    "mechanism": SKELETON_MECHANISM,
    "perspective": SKELETON_PERSPECTIVE,
    "rules": SKELETON_RULES,
    "refuse": SKELETON_REFUSE,
}

CANDIDATES = """# 候选台账

来源：（待填：对象与获取方式）
状态：（待填：已筛 / 未筛）

| # | 候选机制 | 层级 | 锚点 | 三重验证 |
|---|---|---|---|---|
| 1 | （待填） |  |  |  |
"""

UNKNOWNS = """# 未知台账

| 未知 | 为什么解不了 | 需要什么才能解 |
|---|---|---|
| （待填） |  |  |
"""


def norm_text(lines):
    return gate_mod.norm_text(lines)


def fingerprint(lines):
    return gate_mod.fingerprint(lines)


def parse_lines(spec):
    return gate_mod.parse_lines(spec)


def read_jsonl(path):
    return gate_mod.read_jsonl(path)


def write_jsonl(path, rows):
    txt = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else "")
    path.write_text(txt, encoding="utf-8")


def artifacts_of(ddir):
    """产物 = distill 目录下除 evidence/notes/raw 外的 md，排除备份。"""
    out = []
    for p in ddir.rglob("*.md"):
        if any(part in ("raw", "notes") for part in p.parts):
            continue
        if ".bak" in p.name:
            continue
        out.append(p)
    return out


def entry_state(ddir, e):
    """在 gate 的 dead/changed 基础上加 aging。顺序：dead > changed > aging > ok。"""
    st, detail = gate_mod.evidence_state(Path(ddir) / "evidence.jsonl", e)
    if st != "ok":
        return st, detail
    obs = e.get("observed_at", "")
    try:
        days = (date.today() - datetime.strptime(obs, "%Y-%m-%d").date()).days
    except ValueError:
        return "aging", "observed_at 缺失或格式错"
    if days > 30:
        return "aging", f"已 {days} 天未复核"
    return "ok", ""


def cmd_init(args):
    if not SLUG_RE.match(args.slug):
        print("slug 只能用小写字母、数字、连字符，且不以连字符开头", file=sys.stderr)
        return 4
    root = Path(args.root)
    ddir = root / f"distill-{args.slug}"
    main = ddir / "report.md"
    if ddir.exists():
        if not args.force:
            print(f"已存在：{ddir}（加 --force 才覆盖骨架）")
            return 3
        if main.exists() and "（待填" not in main.read_text(encoding="utf-8", errors="replace"):
            print(f"主产物已有内容，拒绝覆盖：{main}", file=sys.stderr)
            return 3
    for sub in ("raw", "notes"):
        (ddir / sub).mkdir(parents=True, exist_ok=True)
    (ddir / "raw" / ".gitkeep").write_text("", encoding="utf-8")
    (ddir / "notes" / "candidates.md").write_text(CANDIDATES, encoding="utf-8")
    main.write_text(SKELETONS[args.type].replace("{slug}", args.slug).replace("{src}", args.source or "（待填：获取方式与版本）"), encoding="utf-8")
    (ddir / "unknowns.md").write_text(UNKNOWNS, encoding="utf-8")
    ev = ddir / "evidence.jsonl"
    if not ev.exists():
        ev.write_text("", encoding="utf-8")
    print(f"已生成：{ddir}")
    print("   report.md / notes/candidates.md / unknowns.md / evidence.jsonl / raw/")
    return 0


def iter_containers(root):
    """找出 root 下所有 distill-* 容器，容忍按域分桶的嵌套布局。

    原先假设 `out/distill-*` 是平铺的，2026-11-09 DSH 目录按域隔离后产物变成
    `runtime/out/<bucket>/distill-*`，平铺 glob 会一份都找不到——门禁于是静默通过。
    限制相对深度 ≤3 且跳过 raw/notes 下的快照副本，避免把素材里的仓库副本当容器。
    """
    root = Path(root)
    if root.is_dir() and root.name.startswith("distill-"):
        return [root]
    out = []
    for p in sorted(root.rglob("distill-*")):
        if not p.is_dir():
            continue
        rel = p.relative_to(root).parts
        if len(rel) <= 3 and "raw" not in rel and "notes" not in rel:
            out.append(p)
    return out


def expand_gate_targets(targets, recursive):
    """--recursive 时把目录展开成产物 md；默认行为不变，原样返回。

    只自动收 distill-* 容器（含分桶嵌套布局），非 distill-* 目录不自动展开——
    out 下有大量其他任务的素材，全量 rglob 会把它们误判成产物（2026-11-09 实测
    一次拉出 308 份）。raw/notes 与备份仍排除。
    """
    out = []
    for raw in targets:
        p = Path(raw)
        if recursive and p.is_dir():
            containers = iter_containers(p)
            hits = []
            for c in containers:
                hits.extend(
                    f for f in c.rglob("*.md")
                    if not any(part in ("raw", "notes") for part in f.parts)
                    and ".bak" not in f.name
                    # unknowns.md 是 init 生成的待填中间件（与 notes/candidates.md 同性质），
                    # 不是产物，自动展开时排除；显式手工指定仍会判，不拦用户的显式行为。
                    and f.name != "unknowns.md"
                )
            out.extend(hits if hits else [p])
        else:
            out.append(p)
    return out


def cmd_gate(args):
    results = []
    recursive = getattr(args, "recursive", False)
    for p in expand_gate_targets(args.targets, recursive):
        # 中间件不是产物：notes/raw 下的台账不声称结论，判据不适用（S9.5「判据过度」处置）
        if "notes" in p.parts or "raw" in p.parts:
            print(f"[SKIP] {p} — 中间件不进 gate（notes/raw 不声称结论）",
                  file=sys.stderr if args.json else sys.stdout)
            continue
        target = gate_mod.pick_target(str(p)) if p.is_dir() else p
        r = gate_mod.check(target, strict_anchor=args.strict_anchor)
        results.append(r)
        if r["status"] == "SKIP":
            print(f"[SKIP] {r['target']} — {r.get('detail', '')}",
                  file=sys.stderr if args.json else sys.stdout)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            if r["status"] == "SKIP":
                continue  # 上面已逐行打印
            print(f"[{r['status']}] {r['target']}")
            for g in r["gaps"]:
                print(f"   gap: {g}")
            for v in r["violations"]:
                print(f"   violation: {v}")
    if any(r["status"] == "FAIL" for r in results):
        summary = "FAIL"
    elif any(r["status"] == "INCOMPLETE" for r in results):
        summary = "INCOMPLETE"
    else:
        summary = "PASS"
    # --json 时把人类可读摘要挪到 stderr，否则 stdout 无法被 json.loads 解析
    print(f"summary: {summary}（{len(results)} 份）", file=sys.stderr if args.json else sys.stdout)
    return {"FAIL": 1, "PASS": 0}.get(summary, 2)


def cmd_index(args):
    root = Path(args.root)
    dirs = iter_containers(root)
    if not dirs:
        print(f"{root} 下没有 distill-* 目录")
        return 2
    report, hard, soft = [], 0, 0
    dirs_info = []
    for ddir in dirs:
        ev_path = ddir / "evidence.jsonl"
        rows = read_jsonl(ev_path)
        bad = [r for r in rows if "__bad__" in r]
        arts = artifacts_of(ddir)
        refs = {}
        by_key = {(r.get("path"), str(r.get("lines"))): r.get("id")
                  for r in rows if isinstance(r, dict) and r.get("id")}
        for a in arts:
            txt = a.read_text(encoding="utf-8", errors="replace")
            rel_art = a.relative_to(ddir).as_posix()
            for eid in set(EID_RE.findall(txt)):
                refs.setdefault(eid, []).append(rel_art)
            # 路径锚点反查：与证据条目同一处（path+lines）即等同引用该 id，两种写法等价
            for anc in set(gate_mod.ANCHOR_FILE_RE.findall(txt)):
                resolved = gate_mod.resolve_anchor_path(a, anc)
                if resolved is None:
                    continue
                try:
                    rel_raw = resolved.resolve().relative_to(ddir.resolve()).as_posix()
                except ValueError:
                    continue
                eid = by_key.get((rel_raw, anc.rsplit(":", 1)[1]))
                if eid:
                    refs.setdefault(eid, []).append(rel_art)
        states, dangling = {}, []
        for eid, where in refs.items():
            if not any(r.get("id") == eid for r in rows):
                dangling.append((eid, where))
        for r in rows:
            if "__bad__" in r:
                hard += 1
                report.append(f"[坏行] {ddir.name}/evidence.jsonl: {r['__bad__'][:60]}")
                continue
            st, detail = entry_state(ddir, r)
            states[r.get("id", "?")] = st
            r["supports"] = refs.get(r.get("id"), [])
            if st in ("dead", "changed"):
                hard += 1
                report.append(f"[{st}] {ddir.name} {r.get('id')} {r.get('path')}:{r.get('lines')} — {detail}")
            elif st == "aging":
                soft += 1
                report.append(f"[aging] {ddir.name} {r.get('id')} — {detail}")
        for eid, where in dangling:
            hard += 1
            report.append(f"[悬空] {ddir.name} 产物引用了不存在的 {eid}（{', '.join(where)}）")
        if not args.dry_run:
            write_jsonl(ev_path, rows)
        report.insert(0, f"== {ddir.name}: 证据 {len(rows)} 条 / 产物 {len(arts)} 份 / 引用 {len(refs)} 个")
        dirs_info.append({
            "name": ddir.name,
            "evidence": len(rows),
            "artifacts": len(arts),
            "refs": len(refs),
            "problems": [ln for ln in report if ln.startswith("[") and ddir.name in ln],
        })
    if getattr(args, "json", False):
        print(json.dumps({
            "dirs": dirs_info, "hard": hard, "soft": soft,
            "summary": "FAIL" if hard else ("AGING" if soft else "OK"),
        }, ensure_ascii=False, indent=2))
    else:
        for ln in report:
            print(ln)
        if args.dry_run:
            print("（dry-run：未写回 supports）")
    if hard:
        return 1
    return 2 if soft else 0


def cmd_evidence_add(args):
    ddir = Path(args.dir)
    if not ddir.is_dir():
        print(f"distill 目录不存在：{ddir}", file=sys.stderr)
        return 4
    rng = parse_lines(args.lines)
    if not rng:
        print(f"行号非法：{args.lines}", file=sys.stderr)
        return 4
    src = Path(args.path)
    if not src.is_absolute():
        src = ddir / src
    if not src.exists():
        print(f"目标文件不存在：{src}", file=sys.stderr)
        return 4
    lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
    if rng[1] > len(lines):
        print(f"行号越界：文件只有 {len(lines)} 行", file=sys.stderr)
        return 4
    seg = lines[rng[0] - 1:rng[1]]
    if not norm_text(seg):
        print("该区间为空，不能作为证据", file=sys.stderr)
        return 4
    try:
        rel = src.resolve().relative_to(ddir.resolve()).as_posix()
    except ValueError:
        print(f"目标文件必须在 {ddir} 内，产物才自包含", file=sys.stderr)
        return 4
    key = f"{rel}|{args.lines}|{args.level}"
    eid = "E-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    ev_path = ddir / "evidence.jsonl"
    rows = read_jsonl(ev_path)
    if any(r.get("id") == eid for r in rows):
        print(f"已存在，跳过：{eid}")
        return 0
    st = args.statement.strip()
    if len(st) > 120:
        print(f"注意：statement {len(st)} 字符，超 120 的部分会截断（建议先在产物里压成一句）", file=sys.stderr)
    rows.append({
        "id": eid,
        "path": rel,
        "lines": str(args.lines),
        "level": args.level,
        "statement": st[:120],
        "quote_sha1": fingerprint(seg),
        "observed_at": args.date or date.today().isoformat(),
        "source_ref": args.source or "（待填：commit 或抓取日期）",
        "supports": [],
    })
    write_jsonl(ev_path, rows)
    print(f"已写入 {eid}  {rel}:{args.lines}  [{args.level}]  {args.statement.strip()[:40]}")
    return 0


def cmd_stamp(args):
    """建立/更新产物的写入基线（notes/.write-manifest.json）。

    gate 只读比对基线、自己不写，所以基线只能由这里显式建立。
    每次确认产物内容正确后跑一次；之后文件被外部程序改写，gate 就会报 GAP。
    """
    f = Path(args.file)
    if not f.is_file():
        print(f"产物文件不存在：{f}", file=sys.stderr)
        return 4
    root = gate_mod.container_root(f)
    mpath = gate_mod.write_manifest_path(f)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            manifest = {}
    try:
        rel = f.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        print(f"产物必须在容器 {root} 内，基线才自包含", file=sys.stderr)
        return 4
    sha = hashlib.sha256(
        f.read_text(encoding="utf-8", errors="replace").encode("utf-8")).hexdigest()
    manifest[rel] = {"sha256": sha,
                     "stamped_at": datetime.now().isoformat(timespec="seconds")}
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                     encoding="utf-8")
    print(f"已基线 {rel}  sha256={sha[:12]}…")
    return 0


def repo_commit(ddir, rel):
    """从 raw/<repo>/.git 取短哈希。取不到返回 None（调用方负责标未记录）。"""
    parts = rel.split("/")
    if len(parts) < 3 or parts[0] != "raw":
        return None
    repo = Path(ddir) / "raw" / parts[1]
    if not (repo / ".git").exists():
        return None
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=15)
        if head.returncode != 0 or not head.stdout.strip():
            return None
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=15)
        return head.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return None


def cmd_evidence_rebind(args):
    ddir = Path(args.dir)
    ev_path = ddir / "evidence.jsonl"
    if not ev_path.exists():
        print(f"没有证据库：{ev_path}", file=sys.stderr)
        return 4
    rows = read_jsonl(ev_path)
    changed, unresolved = 0, []
    for r in rows:
        if "__bad__" in r:
            continue
        rel = r.get("path", "")
        val = repo_commit(ddir, rel)
        if not val:
            unresolved.append(f"{r.get('id')} {rel}")
            continue
        want = f"commit:{val}"
        if r.get("source_ref") != want:
            r["source_ref"] = want
            changed += 1
    if args.dry_run:
        print(f"（dry-run）可回填 {changed} 条，未解析 {len(unresolved)} 条")
    else:
        write_jsonl(ev_path, rows)
        print(f"已回填 {changed} 条 / 共 {len(rows)} 条，未解析 {len(unresolved)} 条")
    for u in unresolved[:5]:
        print("  未解析：" + u)
    return 0 if not unresolved else 2


def cmd_scan(args):
    """只读扫描：列出产物里所有文件锚点，逐个验可解析性。不改任何文件。"""
    root = Path(args.root)
    dirs = iter_containers(root)
    if not dirs:
        print(f"{root} 下没有 distill-* 目录", file=sys.stderr)
        return 2
    bad, total = [], 0
    for ddir in dirs:
        for art in artifacts_of(ddir):
            try:
                txt = art.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                bad.append(f"{art.relative_to(ddir).as_posix()} 读不了：{exc}")
                continue
            for anc in sorted(set(ANCHOR_RE.findall(txt))):
                total += 1
                ok, why = gate_mod.resolve_anchor(art, anc)
                if not ok:
                    bad.append(f"{ddir.name}/{art.relative_to(ddir).as_posix()} -> {why}")
    if getattr(args, "json", False):
        print(json.dumps({
            "dirs": [d.name for d in dirs], "anchors": total,
            "problems": bad, "summary": "OK" if not bad else "FAIL",
        }, ensure_ascii=False, indent=2))
    else:
        print(f"扫描 {len(dirs)} 个目录 / {total} 处锚点，问题 {len(bad)} 处")
        for b in bad[:20]:
            print("  " + b)
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(prog="distill", description="distill-anything 执行层")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="生成产物骨架")
    p_init.add_argument("slug")
    p_init.add_argument("--type", required=True, choices=list(TYPE_DIR))
    p_init.add_argument("--root", default="out")
    p_init.add_argument("--source", default="")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_gate = sub.add_parser("gate", help="校验产物")
    p_gate.add_argument("targets", nargs="+")
    p_gate.add_argument("--json", action="store_true")
    p_gate.add_argument("--recursive", action="store_true",
                        help="目录递归收集产物 md（raw/notes 仍 SKIP），默认关")
    p_gate.add_argument("--strict-anchor", action="store_true",
                        help="要求正文 E id 占锚点总数 ≥50%%（仅对有证据库且 ≥5 条的产物生效）")
    p_gate.set_defaults(func=cmd_gate)

    p_idx = sub.add_parser("index", help="校验证据库")
    p_idx.add_argument("--root", default="out")
    p_idx.add_argument("--dry-run", action="store_true")
    p_idx.add_argument("--json", action="store_true", help="输出 JSON")
    p_idx.set_defaults(func=cmd_index)

    p_ev = sub.add_parser("evidence", help="证据条目")
    ev_sub = p_ev.add_subparsers(dest="evcmd", required=True)
    p_add = ev_sub.add_parser("add")
    p_add.add_argument("--dir", required=True, help="out/distill-<slug>")
    p_add.add_argument("--path", required=True, help="相对该目录的路径，如 raw/x/SKILL.md")
    p_add.add_argument("--lines", required=True)
    p_add.add_argument("--level", required=True, choices=["O", "D", "I"])
    p_add.add_argument("--statement", required=True)
    p_add.add_argument("--source", default="")
    p_add.add_argument("--date", default="")
    p_add.set_defaults(func=cmd_evidence_add)

    p_rb = ev_sub.add_parser("rebind", help="按 raw/<repo>/.git 回填真实 commit")
    p_rb.add_argument("--dir", required=True)
    p_rb.add_argument("--dry-run", action="store_true")
    p_rb.set_defaults(func=cmd_evidence_rebind)

    p_scan = sub.add_parser("scan", help="只读扫描锚点可解析性")
    p_scan.add_argument("--root", default="out")
    p_scan.add_argument("--json", action="store_true", help="输出 JSON")
    p_scan.set_defaults(func=cmd_scan)

    p_stamp = sub.add_parser("stamp", help="建立产物写入基线（供 gate 比对改写）")
    p_stamp.add_argument("file", help="产物 md 的路径")
    p_stamp.set_defaults(func=cmd_stamp)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
