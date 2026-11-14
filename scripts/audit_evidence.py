#!/usr/bin/env python3
"""体检一个或多个产物容器：具体性密度 / raw 材料进证据率 / 上游原文漂移 / 叙述型单源率 / 实现层事实实心率。

只输出观察，不给判定——判定仍由 gate 做。五块可以分开看：
  密度   结论行有没有具体数字、原话、E id、路径行号、日期（判断是不是空话）
  覆盖   raw 里的实质材料有多少进了 evidence.jsonl（判断有没有读了不写）
  漂移   raw 原文与上游现在的内容是否一致（需要 --remote，且本机有 gh）
  叙述   挂了 E id 的结论里，有多少条的所有锚点都落在对象自述文档上
         （README/SKILL/AGENTS/CLAUDE）——那是复述对象自己的说法，读者读 README
         就能拿到，属增量为零的篇幅。raw 里本来只有文档时不告警，因为 100% 是
         结构性的，该查的是采集层。只能抓「全部锚点都在自述文档」这一形态，
         转述型复述（把 README 的话换个说法）抓不到。
  实现层 「实现层事实」节里每条断言是否至少含一个能在 raw 原文里命中的具体符号
         （标识符/常量/环境变量名）。只写「有很多状态，分别对应不同情况」算空写。
         只对机制型且 raw 含代码/配置的对象出数；正则片段与普通英文词不算符号。

用法：
  python scripts/audit_evidence.py <产物目录或容器父目录> [--remote] [--json]
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
# 代码后缀必须进白名单：node/Go/Rust 仓库的实现层标识符只在 .js/.mjs/.go 里，
# 白名单漏掉它们会让「实心率」把写对的一节读成 0%（distill-distilly-repo 实证）。
CODE_SUFFIX = {".js", ".mjs", ".cjs", ".jsx", ".tsx", ".go", ".rs", ".java", ".kt",
               ".rb", ".php", ".sh", ".ps1", ".c", ".h", ".cc", ".cpp", ".cs",
               ".swift", ".lua", ".sql", ".proto"}
MATERIAL = {".md", ".txt", ".ts", ".py", ".json", ".csv", ".jsonl",
            ".toml", ".yml", ".yaml"} | CODE_SUFFIX
# 对象自述文档：讲「自己是什么」，不是可复现的行为证据。
NARRATIVE_NAMES = {"readme.md", "skill.md", "agents.md", "claude.md"}
# 只有纯文本才算叙述材料；代码、配置、数据一律算「可读的非自述材料」。
DOC_SUFFIX = {".md", ".txt"}
NARR_RATIO_ALERT = 0.4   # 与 gate 的 UNMARKED_RATIO_FAIL 同源：两条里有一条在复述自述
NARR_EID_MIN = 5         # 与 gate 的 ANCHOR_MIN 同源：样本少于 5 条不下结论
EID_RE = re.compile(r"E-[0-9a-f]{8}")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# 只认「像标识符」的符号，不认普通英文词：带下划线（needs_configuration）、驼峰
# （planSetupActions）、或点号连接的限定名（inspection.status）。普通英文单词在任何
# README 里都出现，认它等于把「写了 the setup」判成有事实。
SYMBOL = re.compile(r"[A-Za-z][A-Za-z0-9_.]*(?:_[A-Za-z0-9]+)+|[a-z]+[A-Z][A-Za-z0-9]*|[a-z]+[.][a-z]+")
IMPL_RATIO_ALERT = 0.4   # 与 NARR_RATIO_ALERT / gate 的 UNMARKED_RATIO_FAIL 同源
IMPL_ALERT_MIN = 3       # 与 gate 的 ANCHOR_SAMPLE_MIN 同源：少于 3 条不下结论



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


def evidence_map(container):
    """E id -> 相对路径。叙述型单源率要按条查锚点落在哪类材料上。"""
    ev = container / "evidence.jsonl"
    if not ev.exists():
        return {}
    got = {}
    for line in ev.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        pid = (rec.get("id") or "").strip()
        p = (rec.get("path") or "").replace("\\", "/")
        if pid and p:
            got[pid] = p
    return got


def cited_paths(container):
    return set(evidence_map(container).values())


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


def narrative(container):
    """叙述型单源率：挂 E id 的结论里，全部锚点都落在自述文档上的比例（证实类的可机判部分）。"""
    p = product_of(container)
    ev = container / "evidence.jsonl"
    if not p or not ev.exists():
        return None
    paths = evidence_map(container)
    lines = [ln.strip() for ln in body_of(p).splitlines() if MARK.search(ln)]
    eid = narr = unknown = 0
    for ln in lines:
        ids = EID_RE.findall(ln)
        if not ids:
            continue
        ps = [paths.get(i) for i in ids]
        if any(not x for x in ps):
            unknown += 1      # id 不在本容器证据库，锚点类型判不了，不计入分母
            continue
        eid += 1
        if all(Path(x).name.lower() in NARRATIVE_NAMES for x in ps):
            narr += 1
    raw = container / "raw"
    mixed = False
    if raw.exists():
        for f in raw.rglob("*"):
            if (f.is_file() and f.name != ".gitkeep" and f.stat().st_size > 0
                    and f.suffix.lower() not in DOC_SUFFIX):
                mixed = True
                break
    return {"container": container.name, "conclusions": len(lines),
            "eid_conclusions": eid, "narrative_only": narr, "unknown_eid": unknown,
            "ratio": (narr / eid) if eid else 0.0, "mixed_material": mixed}


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


def implement(container):
    """实现层事实实心率：本节每有一条挂标记的断言，至少含一个能在 raw 原文里命中的
    具体符号（标识符/常量/环境变量名），才算「实心」。全节只有中文概括 = 空写。
    只有 raw 含非文档材料（代码/配置/数据）的对象才看这一节：仅文档对象没有实现层。
    """
    p = product_of(container)
    if not p:
        return None
    body = body_of(p).splitlines()
    # 只有机制型产物才谈「实现层」：技能库、方法论流派这类对象 raw 里也常带脚本，
    # 但它们的产物讲的是做法与纪律，没有状态机可写。与判据 6/7 的产物型条件化同源。
    mechanic = any(HEADING.match(ln) and ("结构地图" in ln or "可搬机制" in ln) for ln in body)
    title_at = None
    level = 0
    for i, ln in enumerate(body):
        m = HEADING.match(ln)
        if m and "实现层" in m.group(2):
            title_at, level = i, len(m.group(1))
            break
    raw = container / "raw"
    code_material = False
    index = []
    if raw.exists():
        for f in raw.rglob("*"):
            if not f.is_file() or f.name == ".gitkeep" or f.suffix.lower() not in MATERIAL:
                continue
            if f.suffix.lower() not in DOC_SUFFIX:
                code_material = True
            try:
                index.append(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    haystack = "\n".join(index)
    marked = solid = 0
    if title_at is not None:
        for ln in body[title_at + 1:]:
            m = HEADING.match(ln)
            if m and len(m.group(1)) <= level:
                break
            if not MARK.search(ln):
                continue
            marked += 1
            toks = SYMBOL.findall(EID_RE.sub(" ", ln))
            if any(t in haystack for t in toks):
                solid += 1
    return {"container": container.name, "has_section": title_at is not None,
            "marked": marked, "solid": solid,
            "ratio": (solid / marked) if marked else 0.0,
            "code_material": code_material, "mechanic": mechanic}


def main():
    ap = argparse.ArgumentParser(description="产物证据体检（只报观察，不下判定）")
    ap.add_argument("target", help="产物文件、容器目录或容器父目录")
    ap.add_argument("--remote", action="store_true", help="核对上游原文是否已变（需要 gh 且联网）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON（回归测试用）")
    args = ap.parse_args()

    root = Path(args.target)
    if not root.exists():
        print(f"路径不存在：{root}", file=sys.stderr)
        return 4

    cs = containers(root)
    dens = [(c, density(c)) for c in cs]
    dens = [(c, d) for c, d in dens if d is not None]
    thin = [c.name for c, (total, _, ratio) in dens if ratio < 0.5 and total >= 10]

    cov = [(c, coverage(c)) for c in cs]
    cov = [(c, v) for c, v in cov if v is not None]

    narr = [r for r in (narrative(c) for c in cs) if r is not None]
    alert = [r["container"] for r in narr
             if r["mixed_material"] and r["eid_conclusions"] >= NARR_EID_MIN
             and r["ratio"] >= NARR_RATIO_ALERT]

    impl = [r for r in (implement(c) for c in cs) if r is not None]
    impl_alert = [r["container"] for r in impl
                  if r["code_material"] and r["mechanic"] and (
                      not r["has_section"]
                      or (r["marked"] >= IMPL_ALERT_MIN and r["ratio"] < IMPL_RATIO_ALERT))]

    drifts = []
    if args.remote:
        drifts = [(c, r) for c, r in ((c, drift(c)) for c in cs) if r is not None]

    if args.json:
        payload = {
            "density": [{"container": c.name, "conclusions": t, "concrete": k,
                         "ratio": round(rt, 4)} for c, (t, k, rt) in dens],
            "density_thin": thin,
            "coverage": [{"container": c.name, "material": t, "cited": h,
                          "ratio": round(h / t, 4), "miss_sample": m}
                         for c, (t, h, m) in cov],
            "narrative": [{**r, "ratio": round(r["ratio"], 4)} for r in narr],
            "narrative_alert": alert,
            "implement": [{**r, "ratio": round(r["ratio"], 4)} for r in impl],
            "implement_alert": impl_alert,
            "drift": [{"container": c.name, "repo": r["repo"], "same": r["same"],
                       "changed": r["changed"], "miss": r["miss"]} for c, r in drifts],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("== 具体性密度（结论行）==")
    print(f"{'容器':34}{'结论':>5}{'具体':>5}{'密度':>7}")
    for c, (total, concrete, ratio) in dens:
        print(f"{c.name:34}{total:>5}{concrete:>5}{ratio:>7.0%}")
    if thin:
        print("  低密度（<50% 且结论≥10 条）：" + "、".join(thin))

    print("\n== raw 材料进证据率 ==")
    print(f"{'容器':34}{'材料':>5}{'进库':>5}{'覆盖':>7}  未进库（样本）")
    for c, (total, hit, miss) in cov:
        sample = "、".join(miss) if miss else "—"
        print(f"{c.name:34}{total:>5}{hit:>5}{hit / total:>7.0%}  {sample}")

    print("\n== 叙述型单源率（证实类可机判部分）==")
    print(f"{'容器':34}{'结论':>5}{'挂Eid':>6}{'全自述':>7}{'占比':>7}  材料")
    for r in narr:
        mark = "含非文档" if r["mixed_material"] else "仅文档"
        note = f"  (id 不在库：{r['unknown_eid']})" if r["unknown_eid"] else ""
        print(f"{r['container']:34}{r['conclusions']:>5}{r['eid_conclusions']:>6}"
              f"{r['narrative_only']:>7}{r['ratio']:>7.0%}  {mark}{note}")
    if alert:
        print(f"  含非文档材料却仍全用自述下结论（≥{NARR_RATIO_ALERT:.0%} 且挂 id 结论≥{NARR_EID_MIN}）："
              + "、".join(alert))
    if narr:
        print("  仅文档对象本表不适用：100% 是结构性的，要查的是采集有没有去读代码/实测，不是结论层。")

    impl_rows = [r for r in impl if r["code_material"] and r["mechanic"]]
    if impl_rows:
        print("\n== 实现层事实实心率（仅机制型且 raw 含代码/配置材料的对象）==")
        print(f"{'容器':34}{'有节':>5}{'标记行':>7}{'实心':>5}{'实心率':>7}")
        for r in impl_rows:
            flag = "—" if not r["has_section"] else f"{r['ratio']:>7.0%}"
            print(f"{r['container']:34}{'是' if r['has_section'] else '否':>5}"
                  f"{r['marked']:>7}{r['solid']:>5}{flag:>7}")
        if impl_alert:
            print(f"  缺本节或本节空写（线索，不是判决：对象不是可执行系统时实现层不适用；"
                  f"缺节，或实心率<{IMPL_RATIO_ALERT:.0%} 且标记行≥{IMPL_ALERT_MIN}）："
                  + "、".join(impl_alert))
        print("  实心=该行至少一个具体符号能在 raw 原文里命中；只写「有很多状态」不算。"
              "技能库/方法论型对象不进本表——含代码材料不等于该写实现层。")


        print(f"{'容器':34}{'仓库':34}{'一致':>5}  变动文件")
        for c, r in drifts:
            changed = "、".join(r["changed"]) if r["changed"] else "—"
            miss = f"  (取不到：{'、'.join(r['miss'])})" if r["miss"] else ""
            print(f"{c.name:34}{r['repo']:34}{r['same']:>5}  {changed}{miss}")

    print("\n说明：以上仅为观察。是否达标仍以 gate 结论为准；漂移只说明原文变了，不等同于产物断言已错；"
          "叙述型单源只抓「全部锚点都在自述文档」，转述型复述抓不到。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
