#!/usr/bin/env python3
"""D7 盲化：生成遮蔽评分表、汇总一致/分歧、揭盲。

    d7_blind.py plan --arms any=...,darwin=...,disco=...,none= --questions questions.txt
                       --rounds 3 --seed 7 --out sheet.json
    d7_blind.py score --sheet sheet.json --round 1 --code P2 --c1 y --c2 n --c3 y --c4 n --c5 y
    d7_blind.py report --sheet sheet.json --reveal

判据定义见 references/d7-blind-protocol.md。退出码 0 ok / 1 参数或数据问题。
"""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

CRIT = ("c1", "c2", "c3", "c4", "c5")


def label_map(arms, seed):
    """确定性打乱：同 seed 同结果，避免每轮换一批标签导致无法复现。"""
    rng = random.Random(seed)
    names = list(arms)
    rng.shuffle(names)
    codes = [f"P{i}" for i in range(1, len(names) + 1)]
    return {code: name for code, name in zip(codes, names)}, names


def cmd_plan(args):
    arms = dict(kv.split("=", 1) for kv in args.arms.split(","))
    questions = [q.strip() for q in Path(args.questions).read_text(encoding="utf-8").splitlines() if q.strip()]
    if not questions:
        print("问题清单为空", file=sys.stderr)
        return 1
    answers = {}
    if args.answers:
        for name in arms:
            p = Path(args.answers) / f"{name}.md"
            answers[name] = p.read_text(encoding="utf-8").strip() if p.exists() else ""
    # 每个问题一套答案（ans/q1/any.md …），避免同一段文本答五个问题
    if args.answers:
        root = Path(args.answers)
        for qi in range(1, len(questions) + 1):
            qd = root / f"q{qi}"
            if not qd.is_dir():
                continue
            for name in arms:
                p = qd / f"{name}.md"
                if p.exists():
                    answers[(qi, name)] = p.read_text(encoding="utf-8").strip()
    plan = {"seed": args.seed, "rounds": args.rounds, "questions": questions,
            "arms": arms, "sheets": []}
    for r in range(1, args.rounds + 1):
        mapping, _ = label_map(arms, args.seed + r)
        for qi, q in enumerate(questions, 1):
            order = sorted(mapping, key=lambda c: hashlib.sha1(f"{mapping[c]}{qi}{r}".encode()).hexdigest())
            for idx, code in enumerate(order, 1):
                # 正文按遮蔽后的顺序内联，评分者只看得到文本，看不到它来自哪个臂
                plan["sheets"].append({"round": r, "q": qi, "code": code, "pos": idx,
                                       "text": answers.get((qi, mapping[code]), answers.get(mapping[code], ""))
                                       if answers else "",
                                       "verdict": None})
    # 遮蔽：映射单独存，--reveal 前不打印
    Path(args.out).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    sealed = Path(args.out).with_suffix(".map.json")
    sealed.write_text(json.dumps({str(r): label_map(arms, args.seed + r)[0] for r in range(1, args.rounds + 1)},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {len(plan['sheets'])} 格评分表 -> {args.out}")
    print(f"映射已封存 -> {sealed.name}（评分完成前不要打开）")
    for s in plan["sheets"][:3]:
        print(f"  round{s['round']} Q{s['q']} {s['code']}")
    return 0


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_score(args):
    plan = load(args.sheet)
    vals = {k: getattr(args, k) for k in CRIT}
    hit = sum(1 for v in vals.values() if v == "y")
    found = False
    for s in plan["sheets"]:
        if s["round"] == args.round and s["code"] == args.code and (args.q == 0 or s["q"] == args.q):
            s["verdict"] = {"crit": vals, "hit": hit}
            found = True
    if not found:
        print(f"表里没有 round{args.round} {args.code} Q{args.q}", file=sys.stderr)
        return 1
    Path(args.sheet).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已记录 round{args.round} {args.code} Q{args.q}: {hit}/5")
    return 0


def majority(vals):
    if not vals:
        return None, 0
    best = max(set(vals), key=lambda v: (vals.count(v), v))
    return best, vals.count(best)


def cmd_report(args):
    plan = load(args.sheet)
    mapping = (json.loads(Path(args.sheet).with_suffix(".map.json").read_text(encoding="utf-8"))
               if args.reveal else {})
    print(f"问题 {len(plan['questions'])} × 臂 {len(plan['arms'])} × {plan['rounds']} 轮")
    if not args.reveal:
        for s in plan["sheets"]:
            v = s["verdict"]
            print(f"R{s['round']} Q{s['q']} {s['code']} pos{s['pos']} = {v['hit'] if v else '未评'}")
        print("（未揭盲：只给标签）")
        return 0

    # 每轮的标签都重新打乱，所以只能在「轮」这一层先还原成臂名，再跨轮聚合
    per_arm = {}
    issues = []
    for s in plan["sheets"]:
        arm = mapping.get(str(s["round"]), {}).get(s["code"], s["code"])
        if s["verdict"] is None:
            issues.append(f"R{s['round']} {s['code']}({arm}) 未评")
            continue
        per_arm.setdefault(arm, []).append(s["verdict"]["hit"])
    for arm, hits in sorted(per_arm.items()):
        major, cnt = majority(hits)
        stable = "单轮（不判稳定）" if len(hits) < 2 else f"{'是' if cnt >= 2 else '否'}"
        print(f"{arm:<10} 各轮={hits} 多数={major}/{cnt} 稳定={stable}")

    products = {a: h for a, h in per_arm.items() if a != "none"}
    best = {a: majority(h)[0] for a, h in products.items() if h}
    if best and "none" in per_arm:
        top = max(best.values())
        none_hit = majority(per_arm["none"])[0]
        gap = top - none_hit
        print(f"产物最好 {top} vs 空臂 {none_hit}：差 {gap} → {'不可区分' if gap <= 1 else '可区分'}")
        if none_hit >= top:
            print("⚠ 空臂不劣于最好的产物臂：该问题上「有产物」没带来增量")
    if products:
        lo, hi = min(best.values()), max(best.values()) if best else (None, None)
        if hi is not None:
            print(f"产物臂之间：最高 {hi} 最低 {lo} 差 {hi - lo} → {'不可区分' if hi - lo <= 1 else '可区分'}")
    if issues:
        print("未完成：" + "；".join(issues[:6]) + ("…" if len(issues) > 6 else ""))
    return 0


def main():
    ap = argparse.ArgumentParser(prog="d7_blind")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--arms", required=True)
    p.add_argument("--questions", required=True)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--answers", help="目录，内含 <臂名>.md；不传则只出标签表")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_plan)
    s = sub.add_parser("score")
    s.add_argument("--sheet", required=True)
    s.add_argument("--round", type=int, required=True)
    s.add_argument("--code", required=True)
    s.add_argument("--q", type=int, default=0)
    for c in CRIT:
        s.add_argument(f"--{c}", choices=["y", "n"], required=True)
    s.set_defaults(func=cmd_score)
    r = sub.add_parser("report")
    r.add_argument("--sheet", required=True)
    r.add_argument("--reveal", action="store_true")
    r.set_defaults(func=cmd_report)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
