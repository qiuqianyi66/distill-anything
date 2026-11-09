#!/usr/bin/env python3
"""跨派对照评分器：只算机器可判的五维 + 合成维，生成力抽检留占位。

用法：
    python scripts/score_product.py <产物.md> [--json]
    python scripts/score_product.py <产物.md> --selftest      # 用 fixtures 自测打分器
    python scripts/score_product.py <目录> --batch            # 递归给所有产物打分

判据定义见 references/scorecard-crossschool.md（改这里的算法必须同步改那份文件）。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate as gate_mod

SOFT_WORDS = ("可以考虑", "也许", "根据情况", "视情况", "大概", "似乎是")
FORBID_WORDS = ("禁止", "不要", "绝不", "不许", "不能用")
FALLBACK_KEYS = ("兜底", "fallback", "降级", "失败模式")
EID_RE = re.compile(r"E-[0-9a-f]{8}")

# 类型必备段（按标题关键词命中）
SEC_MECH = ("结构地图", "关键决策", "可搬", "不搬", "证据台账", "诚实边界", "未知台账")
SEC_PERSP = ("心智模型", "决策启发式", "表达", "张力", "不做", "证据台账", "诚实边界", "未知台账")
SEC_RULES = ("判据表", "假阳性", "根因", "门禁", "证据台账", "诚实边界", "未知台账")


def read_artifact(path):
    txt = path.read_text(encoding="utf-8", errors="replace")
    body = txt.split("---", 2)[-1] if txt.startswith("---") else txt
    return txt, body.splitlines()


def headings(body):
    names = []
    for ln in body:
        if ln.startswith("#"):
            t = re.sub(r"^#+\s*", "", ln).strip()
            t = re.sub(r"^[\d.、]+", "", t)
            names.append(t)
    return names


def product_type(body, txt):
    if "-perspective" in txt[:400] or any("心智模型" in h for h in headings(body)):
        return "perspective", SEC_PERSP
    if any("判据表" in h for h in headings(body)):
        return "rules", SEC_RULES
    return "mechanism", SEC_MECH


def d1_structure(body, txt):
    kind, need = product_type(body, txt)
    hs = headings(body)
    hit = [k for k in need if any(k in h for h in hs)]
    return round(10 * len(hit) / len(need), 1), f"{kind} 段 {len(hit)}/{len(need)} 缺:{[k for k in need if k not in hit]}"


def d2_evidence(body):
    concl = [ln for ln in body if ln.strip() and not ln.startswith("#") and ln.strip() != "|"]
    marked = [ln for ln in concl if gate_mod.MARK_RE.search(ln) or "|" in ln and gate_mod.MARK_RE.search(ln)]
    anchors = sum(len(gate_mod.ANCHOR_FILE_RE.findall(ln)) + len(EID_RE.findall(ln)) for ln in body)
    chars = max(len("".join(body)), 1)
    per_k = anchors * 1000 / chars
    ratio = len(marked) / len(concl) if concl else 0
    score = round(5 * min(ratio / 0.8, 1) + 5 * min(per_k / 8, 1), 1)
    return score, f"标记 {len(marked)}/{len(concl)} 锚点 {anchors} 每千字 {per_k:.1f}"


def section_rows(body, keys):
    """找含 keys 的标题，返回其下第一个表格的数据行数与行内容。"""
    rows, inside = [], False
    for ln in body:
        if ln.startswith("#"):
            inside = any(k.lower() in ln.lower() for k in keys)
            continue
        if inside and ln.strip().startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if any(k in cells[0] for k in ("触发", "#", "未知", "结论")):
                continue
            rows.append(cells)
    return rows


def d3_fallback(body):
    rows = section_rows(body, FALLBACK_KEYS)
    if not rows:
        return 0.0, "无兜底节"
    return round(10 * min(len(rows) / 5, 1), 1), f"兜底表 {len(rows)} 行"


def d4_unknown(body):
    rows = section_rows(body, ("未知台账",))
    if not rows:
        return 0.0, "无未知台账数据行"
    thin = [r for r in rows if len(r) < 3 or not r[2] or r[2].startswith("（待填")]
    depth = 1 - len(thin) / len(rows)
    score = round(10 * min(len(rows) / 3, 1) * depth, 1)
    return score, f"{len(rows)} 条 / 缺解法 {len(thin)} 条"


def d5_specific(body):
    concl = [ln for ln in body if ln.strip() and not ln.startswith("#") and ln.strip() != "|"]
    bare = [ln for ln in body
            if any(w in ln for w in gate_mod.BANNED + gate_mod.EVAL_WORDS)
            and not gate_mod.MARK_RE.search(ln)]
    soft = [ln for ln in body if any(w in ln for w in SOFT_WORDS)]
    forbids = sum(ln.count(w) for ln in body for w in FORBID_WORDS)
    # 两个半边各 5 分：干净度看裸断言占结论行比例，禁令看显式条款数。
    # 不给「什么都没写」白送分——空文档裸断言比例为 0，但结论行也为 0，干净度记 0。
    clean = 5 * (1 - min(len(bare) / max(len(concl), 1) * 3, 1)) if concl else 0.0
    explicit = 5 * min(forbids / 3, 1)
    score = max(0.0, clean + explicit - 0.5 * min(len(soft), 6))
    return round(min(score, 10.0), 1), f"裸断言 {len(bare)}/{len(concl)} 软化 {len(soft)} 禁令 {forbids}"


def score(path):
    txt, body = read_artifact(path)
    d1, n1 = d1_structure(body, txt)
    d2, n2 = d2_evidence(body)
    d3, n3 = d3_fallback(body)
    d4, n4 = d4_unknown(body)
    d5, n5 = d5_specific(body)
    d6 = round((d3 + d5) / 2, 1)
    total = round(d1 + d2 + d3 + d4 + d5 + d6, 1)
    return {
        "target": str(path),
        "dims": {"D1 结构": d1, "D2 证据": d2, "D3 兜底": d3, "D4 未知": d4,
                 "D5 具体性": d5, "D6 三元件": d6, "D7 生成力": None},
        "total": total,
        "manual": "pending",
        "notes": {"D1": n1, "D2": n2, "D3": n3, "D4": n4, "D5": n5},
    }


def selftest():
    here = Path(__file__).resolve().parent.parent
    good = here / "tests" / "fixtures" / "score-good.md"
    bad = here / "tests" / "fixtures" / "score-bad.md"
    fails = 0
    g = score(good)["dims"]
    b = score(bad)["dims"]
    print(f"{'维度':<12} good  bad")
    for k in ("D1 结构", "D2 证据", "D3 兜底", "D4 未知", "D5 具体性", "D6 三元件"):
        ok = g[k] > b[k]
        fails += 0 if ok else 1
        print(f"{k:<12} {g[k]:>5} {b[k]:>5}  {'ok' if ok else 'FAIL 未区分'}")

    txt = good.read_text(encoding="utf-8")
    base_d3 = score(good)["dims"]["D3 兜底"]
    tmp = Path(good).parent / "_tmp_no_fallback.md"
    stripped = "\n".join(ln for ln in txt.splitlines() if "兜底" not in ln and "降级" not in ln)
    tmp.write_text(stripped, encoding="utf-8")
    d3b = score(tmp)["dims"]["D3 兜底"]
    ok = base_d3 - d3b >= 2
    fails += 0 if ok else 1
    print(f"D3 变异（删兜底节）{base_d3} -> {d3b}  {'ok' if ok else 'FAIL 掉分不足'}")
    tmp.unlink()

    tmp.write_text(good.read_text(encoding="utf-8").replace("[O] ", "").replace("[D] ", "").replace("[I] ", ""),
                   encoding="utf-8")
    d2b = score(tmp)["dims"]["D2 证据"]
    ok = score(good)["dims"]["D2 证据"] - d2b >= 2
    fails += 0 if ok else 1
    print(f"D2 变异（去标记）-> {d2b}  {'ok' if ok else 'FAIL 掉分不足'}")
    tmp.unlink()

    print(f"\nselftest: {'全部通过' if not fails else f'{fails} 项失败'}")
    return 1 if fails else 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 4
    if "--selftest" in args:
        return selftest()
    target = Path(args[0])
    as_json = "--json" in args
    if "--batch" in args or target.is_dir():
        # 只在 distill-* 容器里找产物：整棵 runtime/out 里混着别的桶与第三方 README，
        # 全收进来会给无关文档打分（首版实测：无关 README 也拿 15 分）。
        containers = [d for d in target.rglob("distill-*") if d.is_dir() and not any(
            s in d.parts for s in ("raw", "notes"))]
        if target.is_dir() and target.name.startswith("distill-"):
            containers = [target]
        files = []
        for d in containers:
            for p in sorted(d.glob("*.md")):
                if ".bak" in p.name or p.name in ("unknowns.md",):
                    continue
                files.append(p)
        rows = [score(p) for p in files]
        if as_json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        print(f"{'产物':<48} {'总分':>5}  D1  D2  D3  D4  D5  D6")
        for r in rows:
            d = r["dims"]
            name = Path(r["target"]).name
            print(f"{name:<48} {r['total']:>5}  " + "  ".join(f"{d[k]:>3}" for k in
                  ("D1 结构", "D2 证据", "D3 兜底", "D4 未知", "D5 具体性", "D6 三元件")))
        return 0
    r = score(target)
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"{target.name}: 总分 {r['total']}")
        for k, v in r["dims"].items():
            print(f"  {k}: {v}")
        for k, v in r["notes"].items():
            print(f"    {k}: {v}")
        print("  D7 生成力: 需人工抽检（0-2 分，脚本不算）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
