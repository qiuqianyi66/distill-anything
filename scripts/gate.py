#!/usr/bin/env python3
"""distill-anything 证据门禁。三态输出：PASS / INCOMPLETE / FAIL。

用法：
    python gate.py <产物.md | 产物目录> [--json]

退出码：0=PASS，1=FAIL，2=INCOMPLETE
INCOMPLETE = 证据还没提供（不是违规）；FAIL = 已有结论但无锚点/裸用断言/引用不存在的文件。
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

MARK_RE = re.compile(r"\[(O|D|I)\]")
EID_RE = re.compile(r"E-[0-9a-f]{8}")
ANCHOR_FILE_RE = re.compile(
    r"[A-Za-z0-9_\-./\\]+\.(?:md|ts|tsx|js|jsx|mjs|cjs|py|json|go|java|kt|rs|ps1|sh|yaml|yml|toml|sql|txt|csv|html):\d+(?:-\d+)?"
)
ANCHOR_URL_RE = re.compile(r"https?://[^\s)\]|]+")
BANNED = ["显然", "众所周知", "毫无疑问", "据说", "大概是", "肯定是", "不言而喻", "大家都知道"]
EVAL_WORDS = ["优秀", "很好", "很强", "明显高于", "值得推荐", "值得学习", "没有之一", "应该是", "非常好", "顶级", "完美", "厉害", "毋庸置疑"]
GAP_CHECKS = {"frontmatter", "markers", "anchors"}
EXEMPT_SECTION_KEYWORDS = ("诚实边界", "局限", "未知", "反模式", "不搬", "unknown", "limitation")
REF_RE = re.compile(r"references/[A-Za-z0-9_\-/]+\.md")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
REQUIRED_GROUPS = {
    "证据台账": ["证据台账", "证据链", "evidence"],
    "未知台账": ["未知", "unknown"],
    "诚实边界": ["诚实边界", "边界", "局限", "limitation"],
}
CONCLUSION_MIN_LEN = 15
UNMARKED_RATIO_FAIL = 0.4
MARK_MIN = 8
ANCHOR_MIN = 5
ANCHOR_SAMPLE_MIN = 3
ANCHOR_SAMPLE_RATIO = 0.2
SIZE_WARN_KB = 60
# 严格锚点：正文应以证据 id 为主。仅对「有 evidence.jsonl 且证据 ≥5 条」的产物生效，
# 否则老产物会集体假红。来源：踩坑 2026-11-08（新产物 24 处路径锚点、0 处 E id）。
STRICT_E_RATIO = 0.5
EVIDENCE_MIN_FOR_STRICT = 5
# 思维型（perspective）结构阈值。只对「frontmatter name 以 -perspective 结尾」或「存在
# 以『心智模型』为标题的节」的产物生效，机制型/判据型不参与，避免把三类产物套同一口径。
# 来源：蒸馏 nuwa-skill examples（2026-11-08），它把「心智模型 3-7 个」当硬规则写进方法，
# 但自带的质检脚本从不检查这一条。超过上限=该删没删（VIOLATION），不足=没蒸出来（GAP）。
MIN_MODELS = 3
MAX_MODELS = 7
# 外来技能文件的 frontmatter 特征键。这些键只出现在第三方技能（如 distilly 原版 SKILL.md），
# 我方产物的 frontmatter 只有 name/description/source/updated。
# 判定必须同时要求「缺 source」：source 是我方产物的必备键，单靠外来键会把带 source 的
# 我方产物误 SKIP。来源：out/distilly-study/SKILL.md 实测，2026-11-09。
FOREIGN_FM_KEYS = ("argument-hint", "allowed-tools", "user-invocable")


def pick_target(raw: str) -> Path:
    p = Path(raw)
    if p.is_dir():
        for name in ("SKILL.md", "report.md", "distill.md", "README.md"):
            cand = p / name
            if cand.exists():
                return cand
        return p
    return p


def norm_text(lines):
    """归一化证据片段：去行尾空白、折叠连续空行。CRLF 由 splitlines 消掉。"""
    txt = "\n".join(ln.rstrip() for ln in lines)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def fingerprint(lines):
    return hashlib.sha1(norm_text(lines).encode("utf-8")).hexdigest()[:12]


def parse_lines(spec):
    m = re.match(r"^(\d+)(?:-(\d+))?$", str(spec).strip())
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    return (a, b) if a >= 1 and b >= a else None


def read_jsonl(path):
    rows = []
    p = Path(path)
    if not p.exists():
        # 首次写入前证据库可能根本不存在，返回空列表而不是抛 FileNotFoundError
        return rows
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            rows.append({"__bad__": ln})
    return rows


def find_evidence(target: Path):
    """产物向上最多三层找 evidence.jsonl。"""
    probes = [target.parent, target.parent.parent, target.parent.parent.parent]
    for d in probes:
        p = d / "evidence.jsonl"
        if p.exists():
            return p
    return None


def evidence_state(ev_path: Path, rec: dict):
    """dead / changed / ok。dead 含文件不存在与行号越界。"""
    ddir = Path(ev_path).parent
    rel = rec.get("path", "")
    p = Path(rel) if rel and Path(rel).is_absolute() else (ddir / rel)
    if not rel or not p.exists() or not p.is_file():
        return "dead", "文件不存在"
    rng = parse_lines(rec.get("lines", ""))
    if not rng:
        return "dead", "行号非法"
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return "dead", f"读不了：{exc}"
    if rng[1] > len(lines):
        return "dead", f"行号越界（文件 {len(lines)} 行）"
    if fingerprint(lines[rng[0] - 1:rng[1]]) != rec.get("quote_sha1"):
        return "changed", "该处内容已变"
    return "ok", ""


def anchor_bases(target: Path):
    """锚点可解析的基准目录：产物目录、其父、以及两者各自 raw/ 与其下一层。

    产物常放在 out/distill-x/deep/ 这类子目录，而 raw/ 在项目根，所以两层的 raw 都要看。
    """
    bases = [target.parent, target.parent.parent]
    for host in (target.parent, target.parent.parent):
        rawd = host / "raw"
        if rawd.is_dir():
            bases.append(rawd)
            try:
                bases += [d for d in rawd.iterdir() if d.is_dir()]
            except OSError:
                pass
    seen, out = set(), []
    for b in bases:
        key = str(b.resolve()).lower()
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out


def _slug(s: str) -> str:
    """标题归一化：去 #、去首尾空格、去标点、转小写、空格转 -（与 GitHub 一致，不做模糊匹配）。"""
    s = re.sub(r"^\s*#+\s*", "", s).strip().lower()
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", s)
    return s.replace(" ", "-")


def heading_slugs(p: Path) -> set:
    out = set()
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for ln in txt.splitlines():
        if ln.lstrip().startswith("#"):
            out.add(_slug(ln))
    return out


def _inside(p: Path, root: Path) -> bool:
    """锚点指向的文件是否落在允许的根内。防 `../` 穿出与绝对路径。"""
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _abs_anchor(path_part: str) -> bool:
    """绝对路径/盘符开头一律不认：锚点必须是产物内的相对路径。"""
    return bool(re.match(r"^[A-Za-z]:", path_part)) or path_part.startswith(("/", "\\"))


def resolve_anchor(target: Path, anchor: str):
    """返回 (ok, reason)。

    同名文件在不同 raw 仓库里各有一份时，不猜：行段内容不同即判歧义，要求写全相对路径。
    锚点必须落在产物目录之内（`../` 与绝对路径都判越界），否则等于拿任意系统文件充数。
    """
    path_part, line = anchor.rsplit(":", 1)
    rng = parse_lines(line)
    if not rng:
        return False, f"行号非法 {anchor}"
    if _abs_anchor(path_part):
        return False, f"锚点不许用绝对路径 {anchor}"
    host = target.parent.parent
    valid, longest, outside = [], 0, False
    for b in anchor_bases(target):
        p = b / path_part.replace("\\", "/")
        if not p.is_file():
            continue
        if not _inside(p, host):
            outside = True
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        longest = max(longest, len(lines))
        if rng[1] <= len(lines):
            valid.append((p, fingerprint(lines[rng[0] - 1:rng[1]])))
    if not valid:
        if outside:
            return False, f"锚点越界 {anchor}：不得引用产物目录之外的文件"
        if longest:
            return False, f"行号越界 {anchor}（同名文件最长 {longest} 行）"
        return False, f"文件不存在 {anchor}"
    if len({fp for _, fp in valid}) > 1:
        return False, f"锚点歧义 {anchor}：{len(valid)} 个同名文件内容不同，需写全相对路径"
    return True, ""


def resolve_anchor_path(target: Path, anchor: str):
    """返回唯一可解析的 Path；不存在、越界或歧义均返回 None。规则与 resolve_anchor 一致。

    供 index 把「路径锚点」反查到证据条目：同一处证据两种写法（路径:行 / E-xxxx）应等价。
    """
    path_part, line = anchor.rsplit(":", 1)
    rng = parse_lines(line)
    if not rng or _abs_anchor(path_part):
        return None
    host = target.parent.parent
    valid = []
    for b in anchor_bases(target):
        p = b / path_part.replace("\\", "/")
        if not p.is_file() or not _inside(p, host):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if rng[1] <= len(lines):
            valid.append((p, fingerprint(lines[rng[0] - 1:rng[1]])))
    if not valid or len({fp for _, fp in valid}) > 1:
        return None
    return valid[0][0]


def unknown_rows(body):
    """取「未知台账」节下的表格数据行。"""
    rows, in_sec = [], False
    for ln in body:
        s = ln.strip()
        if s.startswith("#"):
            in_sec = "未知" in s or "unknown" in s.lower()
            continue
        if in_sec and s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not cells or set(cells) <= {"", "-", ":"}:
                continue
            if cells[0] in ("未知",) or "---" in s:
                continue
            rows.append(cells)
    return rows


def strip_code_and_frontmatter(text: str):
    """返回 (正文行列表, frontmatter 字典)。跳过代码块，避免把示例当证据。"""
    lines = text.splitlines()
    body, fm, in_fm, in_code = [], {}, False, False
    if lines and lines[0].strip() == "---":
        in_fm = True
        lines = lines[1:]
    for ln in lines:
        if in_fm:
            if ln.strip() == "---":
                in_fm = False
                continue
            if ":" in ln:
                k, v = ln.split(":", 1)
                fm[k.strip()] = v.strip()
            continue
        if ln.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            body.append(ln)
    return body, fm


def is_conclusion(line: str) -> bool:
    s = line.strip()
    if not s or "|" in s:
        return False
    if s.startswith(("#", ">", "```")):
        return False
    bullet = s.startswith(("- ", "* ", "1. ", "2. ", "3. ")) or bool(re.match(r"^\d+[.)]\s", s))
    return bullet and len(s) >= CONCLUSION_MIN_LEN


def has_any_marker(ln) -> bool:
    """行/段内是否出现任一标记或锚点（三层标记 / 文件锚点 / URL / 证据 id）。

    E id 必须计入：SKILL §0.6 明确「默认用证据 id」，只认路径与 URL 会把纯 E 化的
    产物判成裸结论。这个判定原先在文件里有三份，其中 section_flags 那份漏了 EID_RE，
    与「裸结论」口径不一致——统一到这里。
    """
    return bool(MARK_RE.search(ln) or ANCHOR_FILE_RE.search(ln)
                or ANCHOR_URL_RE.search(ln) or EID_RE.search(ln))


def section_flags(body):
    """按标题切节，返回 (锚点标记, 豁免标记) 两个与 body 等长的列表。

    锚点按「节」绑定而不是逐行绑定：一条机制的四个字段共用一条证据是正常写法。
    豁免节（诚实边界/未知/局限/反模式/不搬）的条目本来就不声称事实，不参与裸结论统计。
    """
    flags = [False] * len(body)
    exempts = [False] * len(body)

    def flush(s, e, title):
        if e <= s:
            return
        seg = body[s:e]
        has = any(has_any_marker(x) for x in seg)
        is_ex = any(k in title for k in EXEMPT_SECTION_KEYWORDS)
        for i in range(s, e):
            flags[i] = has
            exempts[i] = is_ex

    start, title = 0, ""
    for i, ln in enumerate(body):
        if ln.strip().startswith("#"):
            flush(start, i, title)
            start, title = i, ln
    flush(start, len(body), title)
    return flags, exempts


def section_bounds(body, keyword):
    """返回标题含 keyword 的那一节正文的 (起, 止) 行号。没有该节则 (None, None)。

    止于第一个不深于它的后续标题；节内子标题不截断。
    """
    for i, ln in enumerate(body):
        s = ln.strip()
        if s.startswith("#") and keyword in s:
            lv = len(s) - len(s.lstrip("#"))
            for j in range(i + 1, len(body)):
                t = body[j].strip()
                if t.startswith("#") and (len(t) - len(t.lstrip("#"))) <= lv:
                    return i + 1, j
            return i + 1, len(body)
    return None, None


class _Ctx:
    """check 的共享上下文。用 __slots__ 而不是 dataclass：本文件零三方依赖，
    为一个内部结构引入类型样板不值得。跨段复用的中间量挂在这里，分组函数不再互相穿参。"""
    __slots__ = ("target", "text", "body", "joined", "fm", "strict_anchor",
                 "marks", "eids", "file_anchors", "url_anchors", "anchor_total",
                 "checks", "violations", "gaps")

    def __init__(self, target, text, body, joined, fm, strict_anchor):
        self.target = target
        self.text = text
        self.body = body
        self.joined = joined
        self.fm = fm
        self.strict_anchor = strict_anchor
        self.marks = []
        self.eids = []
        self.file_anchors = []
        self.url_anchors = []
        self.anchor_total = 0
        self.checks = []
        self.violations = []
        self.gaps = []


def _empty_result(target, gap):
    """早退结果。两处早退原先各写一份 dict 字面量，字段一多就会漂移。"""
    return {"status": "INCOMPLETE", "target": str(target),
            "checks": [], "gaps": [gap], "violations": []}


def is_foreign(target: Path, fm: dict) -> bool:
    """外来文件不是我方产物，gate 不适用，判 SKIP 而不是 INCOMPLETE。

    两条路径：
    A) frontmatter 带第三方技能键（argument-hint/allowed-tools/user-invocable）且缺 source——
       我方产物必有 source，单靠外来键会误伤带 source 的产物。
    B) 目录链上有 `.foreign` 标记——没有 frontmatter 的现场文件（如事故原始 report）
       没有可识别的字形特征，只能靠显式标记，不猜内容。
    """
    for d in (target.parent, target.parent.parent):
        if (d / ".foreign").exists():
            return True
    return bool(fm) and "source" not in fm and any(k in fm for k in FOREIGN_FM_KEYS)


def container_root(target: Path) -> Path:
    """产物所属容器根：向上找含 notes/ 的目录（最多两层）；找不到就用产物父目录。"""
    for d in (target.parent, target.parent.parent):
        if (d / "notes").is_dir():
            return d
    return target.parent


def write_manifest_path(target: Path) -> Path:
    """写入基线固定放在容器 notes/ 下，不污染产物目录。"""
    return container_root(target) / "notes" / ".write-manifest.json"


def _check_identity(ctx):
    """身份与骨架：frontmatter 是否被改写、必需段落、思维型结构的 3-7 模型与张力。"""
    checks, violations, gaps = ctx.checks, ctx.violations, ctx.gaps
    body, joined, fm, target = ctx.body, ctx.joined, ctx.fm, ctx.target
    text = ctx.text
    # 0 产物是否被 markdown 格式化器二次写坏。判据：首行不是 ---，但紧随其后出现
    # YAML 键——说明本来有 frontmatter，被改成了 ***（或插入了裸空行）。
    # 不查这个会把「文件损坏」误判成「本来就没有 frontmatter 的 report」而放行，
    # 是比漏检更糟的假绿。来源：蒸馏 nuwa-skill 产物落盘后被回写，2026-11-08 实测。
    raw_lines = [ln.strip() for ln in text.splitlines()]
    if raw_lines and raw_lines[0] != "---":
        yaml_probe = [ln for ln in raw_lines[:12]
                      if re.match(r"^(name|description|version|source|updated)\s*:", ln)]
        if yaml_probe:
            checks.append({"name": "fm-mangled", "ok": False, "kind": "VIOLATION",
                           "detail": f"首行是 `{raw_lines[0]}`，但随后出现 YAML 键——frontmatter 被改写"})
            violations.append(
                "frontmatter 被 markdown 格式化器改写（首行分隔符不是 `---`）："
                "把开头的 `***` 改回 `---`、删掉键之间插入的空行后复跑"
            )
    # 1 frontmatter
    if fm.get("name") and fm.get("description"):
        checks.append({"name": "frontmatter", "ok": True, "detail": "name+description"})
    elif not fm:
        checks.append({"name": "frontmatter", "ok": None, "detail": "无 frontmatter（report 型可豁免）"})
        gaps.append("缺 frontmatter（若为 report.md 可豁免）")
    else:
        checks.append({"name": "frontmatter", "ok": False, "detail": "缺 name 或 description"})
        gaps.append("frontmatter 不完整")
    # 2 必需段落
    for group, keys in REQUIRED_GROUPS.items():
        hit = any(k.lower() in joined.lower() for k in keys)
        checks.append({"name": f"section:{group}", "ok": hit, "detail": "命中" if hit else "缺失"})
        if not hit:
            gaps.append(f"缺「{group}」段")
    # 2b perspective 结构（条件触发，机制型/判据型不参与）
    ms, me = section_bounds(body, "心智模型")
    is_persp = (fm.get("name") or "").rstrip().endswith("-perspective") or ms is not None
    if is_persp:
        n_model = 0
        if ms is not None:
            # 条目编号三种等价写法：`### 1.` / `### 模型1:` / `### M1`。
            # 只认数字会把 M1 型产物数成 0（method-schools / user-thinking 实测假红）。
            n_model = sum(
                1 for ln in body[ms:me]
                if re.match(r"^###\s*(?:模型|M)?\s*\d+", ln.strip())
            )
        if n_model > MAX_MODELS:
            checks.append({"name": "persp:models", "ok": False, "detail": f"{n_model} 个，超过 {MAX_MODELS}"})
            violations.append(f"心智模型 {n_model} 个，超过 {MAX_MODELS}：该删没删，候选全留等于没筛选")
        elif n_model < MIN_MODELS:
            checks.append({"name": "persp:models", "ok": False, "detail": f"{n_model} 个，少于 {MIN_MODELS}"})
            gaps.append(f"心智模型只有 {n_model} 个，少于 {MIN_MODELS}：没蒸出来，补采集或降级为判据型")
        else:
            checks.append({"name": "persp:models", "ok": True, "detail": f"{n_model} 个"})

        ts, te = section_bounds(body, "张力")
        t_n = 0
        if ts is not None:
            # 三种合法写法都要认：bullet（`- ` / `* `）、有序列表（`1.` / `1)`）、表格行。
            # 只认 bullet 时，芒格式有序列表与 method-schools 式表格都被数成 0（实测假红 2 次）。
            bullets = sum(
                1 for ln in body[ts:te]
                if re.match(r"^(?:[-*]|\d+[.)])\s+\S", ln.strip())
            )
            trows = [ln.strip() for ln in body[ts:te] if ln.strip().startswith("|")]
            body_rows = [r for r in trows if not re.match(r"^\|[\s:|\-]+\|$", r)]
            # 表格首行是表头，不算条目
            t_n = bullets + (max(len(body_rows) - 1, 0) if body_rows else 0)
        if not t_n:
            # 次优但合法：张力写在某节内的粗体子标题下（如 `**我自己也没想清楚的**（内在张力）：`）。
            # 只认行首是 ** 或 # 的张力行，避免正文随口提到「张力」时误计数。
            for i, ln in enumerate(body):
                s = ln.strip()
                if "张力" in s and s.startswith(("**", "#")):
                    j = i + 1
                    while j < len(body) and not body[j].strip():
                        j += 1
                    while j < len(body) and re.match(r"^(?:[-*]|\d+[.)])\s+\S", body[j].strip()):
                        t_n += 1
                        j += 1
                    if t_n:
                        break
        if t_n == 0:
            checks.append({"name": "persp:tension", "ok": False, "detail": "无内在张力条目"})
            gaps.append("缺「内在张力」条目（至少 1 对未调和的矛盾，调和平了就是假）")
        else:
            checks.append({"name": "persp:tension", "ok": True, "detail": f"{t_n} 条"})

        has_agentic = ("Agentic" in joined) or ("回答工作流" in joined)
        checks.append({
            "name": "persp:agentic",
            "ok": True if has_agentic else None,
            "detail": "命中" if has_agentic else "缺失（建议补：分类→按对象检索→作答，且检索过程不输出）",
        })


def _check_evidence(ctx):
    """证据底座：三层标记数、三类锚点去重计数、严格锚点占比。写回跨段复用的中间量。"""
    checks, violations, gaps = ctx.checks, ctx.violations, ctx.gaps
    body, joined, fm, target = ctx.body, ctx.joined, ctx.fm, ctx.target
    strict_anchor = ctx.strict_anchor
    # 3 三层标记
    marks = MARK_RE.findall(joined)
    checks.append({"name": "markers", "ok": len(marks) >= MARK_MIN, "detail": f"{len(marks)} 处"})
    if len(marks) < MARK_MIN:
        gaps.append(f"证据标记不足（{len(marks)} < {MARK_MIN}）")
    # 4 锚点（三种写法等价：文件锚点、URL、证据 id）
    eids = sorted(set(EID_RE.findall(joined)))
    file_anchors = ANCHOR_FILE_RE.findall(joined)
    url_anchors = ANCHOR_URL_RE.findall(joined)
    # 同一处锚点重复出现不凑数（踩坑 2026-11-08：google-skills 报 8 处，实际只有 4 处不同）
    anchor_total = len(set(file_anchors)) + len(set(url_anchors)) + len(eids)
    checks.append(
        {"name": "anchors", "ok": anchor_total >= ANCHOR_MIN,
         "detail": f"文件 {len(file_anchors)} + URL {len(url_anchors)} + 证据 id {len(eids)}"}
    )
    if anchor_total < ANCHOR_MIN:
        gaps.append(f"锚点不足（{anchor_total} < {ANCHOR_MIN}）")
    # 4b 严格锚点（--strict-anchor）：正文该以证据 id 为主，路径锚点只留白名单场景。
    # 只对「有 evidence.jsonl 且证据 ≥5 条」的产物生效，否则老产物集体假红。
    # 来源：踩坑 2026-11-08（新产物正文 24 处路径锚点、0 处 E id，读者查不到条目）。
    if strict_anchor:
        ev_s = find_evidence(target)
        rows_s = [r for r in read_jsonl(ev_s) if isinstance(r, dict) and r.get("id")] if ev_s else []
        denom = len(set(file_anchors)) + len(set(url_anchors)) + len(eids)
        if len(rows_s) < EVIDENCE_MIN_FOR_STRICT:
            checks.append({"name": "strict-anchor", "ok": None,
                           "detail": f"豁免：证据库 {len(rows_s)} 条 < {EVIDENCE_MIN_FOR_STRICT}"})
        elif denom == 0:
            checks.append({"name": "strict-anchor", "ok": None, "detail": "无锚点，跳过"})
        else:
            ratio_e = len(eids) / denom
            ok_e = ratio_e >= STRICT_E_RATIO
            checks.append({"name": "strict-anchor", "ok": ok_e, "kind": "GAP",
                           "detail": f"E id {len(eids)}/{denom} = {ratio_e:.0%}（要求 ≥{STRICT_E_RATIO:.0%}）"})
            if not ok_e:
                gaps.append(f"证据 id 占比 {ratio_e:.0%} < {STRICT_E_RATIO:.0%}：正文改用 E-xxxx，原文位置写进证据库")
    else:
        checks.append({"name": "strict-anchor", "ok": None, "detail": "未开启"})
    ctx.marks, ctx.eids = marks, eids
    ctx.file_anchors, ctx.url_anchors = file_anchors, url_anchors
    ctx.anchor_total = anchor_total




def _check_conclusions(ctx):
    """结论质量：裸结论按节绑定判豁免，以及裸用断言词。"""
    checks, violations, gaps = ctx.checks, ctx.violations, ctx.gaps
    body, joined, fm, target = ctx.body, ctx.joined, ctx.fm, ctx.target
    marks, anchor_total = ctx.marks, ctx.anchor_total
    # 5 结论行无标记。锚点按节绑定：所在节有锚点则豁免，整节无锚点才算裸结论
    concl = [(i, ln) for i, ln in enumerate(body) if is_conclusion(ln)]
    flags, exempts = section_flags(body)

    def _marked(ln):
        return has_any_marker(ln)

    bare = [ln for i, ln in concl if not _marked(ln) and not flags[i] and not exempts[i]]
    eval_bare = [ln for ln in bare if any(w in ln for w in EVAL_WORDS)]
    ratio = (len(bare) / len(concl)) if concl else 0.0
    has_base = len(marks) >= MARK_MIN and anchor_total >= ANCHOR_MIN
    if len(eval_bare) >= 2:
        checks.append({"name": "conclusions", "ok": False,
                       "detail": f"{len(eval_bare)} 条评价型裸结论（共 {len(concl)} 条结论）"})
        violations.append(f"{len(eval_bare)} 条评价型结论无任何标记或锚点")
        for ln in eval_bare[:3]:
            violations.append("  裸结论：" + ln.strip()[:70])
    elif has_base and len(concl) >= 5 and ratio > UNMARKED_RATIO_FAIL:
        checks.append({"name": "conclusions", "ok": False, "detail": f"{len(bare)}/{len(concl)} 条无标记"})
        violations.append(f"{len(bare)}/{len(concl)} 条结论所在节无任何锚点")
    else:
        checks.append({"name": "conclusions", "ok": True, "detail": f"{len(bare)}/{len(concl)} 未标记"})
        if len(bare) >= 3 and ratio > 0.3:
            gaps.append(f"{len(bare)} 条结论所在节无锚点（可补，不构成违规）")
    # 6 裸用断言词
    banned_lines = []
    for ln in body:
        if any(w in ln for w in BANNED) and not has_any_marker(ln):
            banned_lines.append(ln.strip()[:80])
    if banned_lines:
        checks.append({"name": "banned-words", "ok": False, "detail": f"{len(banned_lines)} 行裸用"})
        violations.append(f"裸用断言词 {len(banned_lines)} 行")
    else:
        checks.append({"name": "banned-words", "ok": True, "detail": "无"})


def _check_references(ctx):
    """引用与存活：相对路径引用、相对链接与页内锚点、抽样存活、E 证据三态、未知台账深度。"""
    checks, violations, gaps = ctx.checks, ctx.violations, ctx.gaps
    body, joined, fm, target = ctx.body, ctx.joined, ctx.fm, ctx.target
    file_anchors, eids = ctx.file_anchors, ctx.eids
    # 7 引用完整性
    missing_refs = []
    if target.is_file():
        for ref in set(REF_RE.findall(joined)):
            if not (target.parent / ref).exists():
                missing_refs.append(ref)
    if missing_refs:
        checks.append({"name": "refs", "ok": False, "detail": f"缺 {len(missing_refs)} 个"})
        violations.append("引用不存在：" + ", ".join(sorted(missing_refs)[:3]))
    else:
        checks.append({"name": "refs", "ok": True, "detail": "全部可达"})
    # 7e 相对链接与锚点：链接目标必须存在，`#锚点` 必须在目标文档里有同名标题
    if target.is_file():
        prose_txt = re.sub(r"```.*?```", " ", joined, flags=re.S)
        bad_links = []
        for tgt in LINK_RE.findall(prose_txt):
            if tgt.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part, _, frag = tgt.partition("#")
            if not path_part:
                continue
            p = target.parent / path_part
            if not p.exists():
                bad_links.append(f"{path_part}（目标不存在）")
                continue
            if frag and p.suffix.lower() == ".md" and _slug(frag) not in heading_slugs(p):
                bad_links.append(f"{tgt}（锚点找不到标题）")
        if bad_links:
            checks.append({"name": "links", "ok": False, "kind": "VIOLATION",
                           "detail": f"{len(bad_links)} 处"})
            violations.append("链接失效：" + "；".join(bad_links[:3]))
        else:
            checks.append({"name": "links", "ok": True, "detail": "全部可达"})
    # 7b 锚点存活：抽样（≤3 全查，否则 20% 且至少 3），确定性抽样保证回归可复现
    file_anchor_list = sorted(set(file_anchors))
    if file_anchor_list:
        n = len(file_anchor_list)
        if n <= ANCHOR_SAMPLE_MIN:
            sample = file_anchor_list
        else:
            sample = sorted(
                file_anchor_list, key=lambda a: hashlib.sha1(a.encode("utf-8")).hexdigest()
            )[: max(ANCHOR_SAMPLE_MIN, int(n * ANCHOR_SAMPLE_RATIO))]
        dead = []
        for a in sample:
            ok_a, why = resolve_anchor(target, a)
            if not ok_a:
                dead.append(why)
        if dead:
            checks.append({"name": "anchor-liveness", "ok": False, "kind": "VIOLATION",
                           "detail": f"{len(dead)}/{len(sample)} 不可解析"})
            violations.append("锚点不可解析：" + "；".join(dead[:3]))
        else:
            checks.append({"name": "anchor-liveness", "ok": True,
                           "detail": f"抽样 {len(sample)}/{n} 全部成立"})
    else:
        checks.append({"name": "anchor-liveness", "ok": None, "detail": "无文件锚点，跳过"})
    # 7c 证据 id 校验：必须存在于最近一层 evidence.jsonl，且指纹未变
    if eids:
        ev = find_evidence(target)
        if ev is None:
            checks.append({"name": "evidence-refs", "ok": False, "kind": "GAP",
                           "detail": f"{len(eids)} 个 id 但无 evidence.jsonl"})
            gaps.append("产物引用了证据 id，但同级/上级没有 evidence.jsonl")
        else:
            byid = {r.get("id"): r for r in read_jsonl(ev) if isinstance(r, dict) and r.get("id")}
            dead, changed = [], []
            for eid in eids:
                rec = byid.get(eid)
                if not rec:
                    dead.append(f"{eid}（无此条目）")
                    continue
                state, why = evidence_state(ev, rec)
                if state == "dead":
                    dead.append(f"{eid}（{why}）")
                elif state == "changed":
                    changed.append(eid)
            if dead:
                checks.append({"name": "evidence-refs", "ok": False, "kind": "VIOLATION",
                               "detail": f"失效 {len(dead)}"})
                violations.append("证据指向已失效：" + "；".join(dead[:3]))
            elif changed:
                checks.append({"name": "evidence-refs", "ok": False, "kind": "GAP",
                               "detail": f"{len(changed)} 条已变"})
                gaps.append("证据内容已变，需重读改断言：" + ", ".join(changed[:3]))
            else:
                checks.append({"name": "evidence-refs", "ok": True,
                               "detail": f"{len(eids)} 个全部成立"})
    else:
        checks.append({"name": "evidence-refs", "ok": None, "detail": "无 id 引用"})
    # 7d 未知台账深度：每行必须写清「需要什么才能解」
    urows = unknown_rows(body)
    thin = [r for r in urows if len(r) < 3 or not r[2] or r[2].startswith("（待填")]
    if urows and not thin:
        checks.append({"name": "unknown-depth", "ok": True, "detail": f"{len(urows)} 条均写清解法"})
    elif urows:
        checks.append({"name": "unknown-depth", "ok": False, "kind": "GAP",
                       "detail": f"{len(thin)}/{len(urows)} 条缺「需要什么」"})
        gaps.append(f"{len(thin)} 条未知没写清「需要什么才能解」")
    else:
        checks.append({"name": "unknown-depth", "ok": None, "detail": "无数据行（缺台账已由 section 检查报）"})


def _check_size(ctx):
    """体积：只做 warn，不参与判定。"""
    checks, violations, gaps = ctx.checks, ctx.violations, ctx.gaps
    target = ctx.target
    # 8 体积
    size_kb = target.stat().st_size / 1024
    checks.append({"name": "size", "ok": True, "detail": f"{size_kb:.1f}KB", "warn": size_kb > SIZE_WARN_KB})


def check(target: Path, strict_anchor: bool = False):
    """门禁主入口。判定逻辑全在 5 个分组函数里，这里只做早退与汇总。"""
    if not target.exists():
        return _empty_result(target, "产物文件不存在")
    if target.is_dir():
        return _empty_result(target, "目录下没有 SKILL.md / report.md / distill.md / README.md")

    text = target.read_text(encoding="utf-8", errors="replace")
    body, fm = strip_code_and_frontmatter(text)
    if is_foreign(target, fm):
        return {"status": "SKIP", "target": str(target), "checks": [],
                "gaps": [], "violations": [],
                "detail": "外来文件（第三方技能/原始现场），判据不适用"}
    ctx = _Ctx(target, text, body, "\n".join(body), fm, strict_anchor)

    # 写入完整性：基线由 `distill stamp` 显式建立，gate 只读，不自己写基线。
    # manifest 缺失=未建立基线，不告警（不惩罚历史）；sha 不匹配=落盘后被外部程序改动。
    # 用完整文件 sha256：frontmatter 与正文任何一处被改都能抓到，不按字形猜（`* ` 与
    # `- ` 语义上无法区分，按字形判就是第四次栽同一类错）。
    mpath = write_manifest_path(target)
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            manifest = {}
        try:
            rel = target.resolve().relative_to(container_root(target).resolve()).as_posix()
        except ValueError:
            rel = target.name
        rec = manifest.get(rel)
        cur_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if rec and rec.get("sha256") != cur_sha:
            ctx.checks.append({"name": "write-integrity", "ok": False, "kind": "GAP",
                               "detail": "与 stamp 基线不一致，落盘后被改动"})
            ctx.gaps.append("产物在 stamp 之后被外部程序改写：确认来源后重跑 distill stamp 重建基线，或还原文件")
        else:
            ctx.checks.append({"name": "write-integrity", "ok": True, "detail": "与基线一致"})
    else:
        ctx.checks.append({"name": "write-integrity", "ok": None,
                           "detail": "未建立写入基线（distill stamp）"})

    _check_identity(ctx)
    _check_evidence(ctx)
    _check_conclusions(ctx)
    _check_references(ctx)
    _check_size(ctx)

    violations, gaps = ctx.violations, ctx.gaps
    status = "FAIL" if violations else ("INCOMPLETE" if gaps else "PASS")
    return {"status": status, "target": str(target), "checks": ctx.checks,
            "gaps": gaps, "violations": violations}

def main():
    ap = argparse.ArgumentParser(description="distill-anything evidence gate")
    ap.add_argument("target", help="产物文件或目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict-anchor", action="store_true",
                    help="要求正文 E id 占锚点总数 ≥50%（仅对有证据库且 ≥5 条的产物生效）")
    args = ap.parse_args()

    result = check(pick_target(args.target), strict_anchor=args.strict_anchor)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["status"] == "SKIP":
        print(f"[SKIP] {result['target']} — {result.get('detail', '')}")
    else:
        print(f"[DISTILL GATE] {result['target']}")
        print(f"status: {result['status']}  (GAP=证据还没给 / VIOLATION=给了结论但没有证据)")
        for c in result["checks"]:
            if c["ok"] in (True, None):
                mark = "ok"
            elif c.get("kind"):
                mark = c["kind"]
            elif c["name"] in GAP_CHECKS or c["name"].startswith("section:"):
                mark = "GAP"
            else:
                mark = "VIOLATION"
            warn = " (warn)" if c.get("warn") else ""
            print(f"  {c['name']:<28} {mark:<10} {c['detail']}{warn}")
        for g in result["gaps"]:
            print(f"  gap: {g}")
        for v in result["violations"]:
            print(f"  violation: {v}")
        if result["violations"]:
            print("fix: 补锚点或删结论；禁止改阈值或改判定")
        elif result["gaps"]:
            print("fix: 补采集/补未知台账后再交付")
        else:
            print("fix: 无需修改")

    sys.exit({"PASS": 0, "FAIL": 1, "SKIP": 0}.get(result["status"], 2))


if __name__ == "__main__":
    main()
