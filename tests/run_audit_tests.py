#!/usr/bin/env python3
"""audit_evidence.py 回归：叙述型单源率（证实类的可机判部分）。

口径：一条挂了 E id 的结论，若**全部**锚点都落在对象自述文档
（README/SKILL/AGENTS/CLAUDE）上，就记一次「叙述型单源」——它只是在复述对象
自己说的话，读者读 README 就能拿到，属增量为零的篇幅。
raw 里本来就只有文档时不告警（100% 是结构性的），要查的是采集层而不是结论层。

用法：python tests/run_audit_tests.py
退出码 0 = 全部符合预期；1 = 有偏差（改判据后必须重跑）
"""
import json
import subprocess
import sys
from pathlib import Path

# 容器 -> (结论数, 挂 E id 的结论数, 其中全叙述型, raw 是否含非文档材料)
CASES = {
    "distill-narr-code": (6, 6, 6, True),
    "distill-narr-docs": (2, 2, 2, False),
    "distill-narr-half": (1, 1, 0, True),
    "distill-narr-mixed": (7, 7, 1, True),
}

# 只有「含非文档材料却仍全用自述下结论」的容器才进警惕名单。
EXPECT_ALERT = {"distill-narr-code"}


def run_audit(audit: Path, target: Path):
    proc = subprocess.run(
        [sys.executable, str(audit), str(target), "--json"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if proc.returncode != 0:
        return None, proc
    try:
        return json.loads(proc.stdout), proc
    except json.JSONDecodeError:
        return None, proc


def report(name, expect, got):
    ok = got == expect
    print(f"{'ok  ' if ok else 'FAIL'} {name:<34} expect={expect!s:<12} got={got!s:<12}")
    return 0 if ok else 1


def main() -> int:
    root = Path(__file__).resolve().parent
    audit = root.parent / "scripts" / "audit_evidence.py"
    fixture = root / "fixtures" / "audit-narr"
    if not audit.exists():
        print(f"FAIL audit_evidence.py 不存在：{audit}")
        return 1

    data, proc = run_audit(audit, fixture)
    if data is None:
        print("FAIL 取不到 JSON 输出（缺 --json 或退出码非 0）")
        if proc.stderr:
            print(proc.stderr.strip()[:800])
        return 1

    rows = {r["container"]: r for r in data.get("narrative", [])}
    failures = 0
    for name, (concl, eid, narr, mixed) in CASES.items():
        r = rows.get(name)
        if r is None:
            print(f"FAIL {name:<34} 不在 narrative 表里")
            failures += 1
            continue
        failures += report(f"{name} conclusions", concl, r["conclusions"])
        failures += report(f"{name} eid_conclusions", eid, r["eid_conclusions"])
        failures += report(f"{name} narrative_only", narr, r["narrative_only"])
        failures += report(f"{name} mixed_material", mixed, r["mixed_material"])

    got_alert = set(data.get("narrative_alert", []))
    failures += report("narrative_alert 集合全等", EXPECT_ALERT, got_alert)

    # 只有文档的对象必须不告警：100% 是结构性的，不是结论层缺陷。
    docs_row = rows.get("distill-narr-docs") or {}
    failures += report(
        "docs-only 不进警惕",
        False,
        "distill-narr-docs" in got_alert,
    )

    print(f"\n{'全部通过' if failures == 0 else f'{failures} 项不符预期'}")
    failures += impl_checks(root, audit)
    return 0 if failures == 0 else 1


# 实现层事实实心率：一节里每条挂标记的断言，若至少含一个能在 raw 原文里命中的
# 具体符号（标识符/常量/环境变量名），算「实心」；全节都只有中文概括的算空写。
# 只有 raw 含非文档材料（代码/配置/数据）的对象才查这一节——仅文档对象没有实现层。
IMPL_CASES = {
    # 容器 -> (有本节, 挂标记行数, 实心行数, raw 含非文档材料)
    "distill-impl-solid": (True, 3, 3, True),
    "distill-impl-hollow": (True, 3, 0, True),
    "distill-impl-none": (False, 0, 0, True),
    "distill-impl-docs": (False, 0, 0, False),
    # 只有 .mjs 原文的仓库：代码后缀若不在读的白名单里，本节会被误判 0% 空写
    "distill-impl-mjs": (True, 2, 2, True),
}
EXPECT_IMPL_ALERT = {"distill-impl-hollow", "distill-impl-none"}


def impl_checks(root: Path, audit: Path) -> int:
    fixture = root / "fixtures" / "audit-impl"
    if not fixture.exists():
        print("FAIL 夹具目录不存在：fixtures/audit-impl")
        return 1
    data, proc = run_audit(audit, fixture)
    if data is None:
        print("FAIL 取不到 JSON 输出（缺 implement 表或退出码非 0）")
        if proc.stderr:
            print(proc.stderr.strip()[:800])
        return 1
    if "implement" not in data:
        print("FAIL JSON 里没有 implement 表")
        return 1

    rows = {r["container"]: r for r in data["implement"]}
    failures = 0
    for name, (has, marked, solid, code) in IMPL_CASES.items():
        r = rows.get(name)
        if r is None:
            print(f"FAIL {name:<34} 不在 implement 表里")
            failures += 1
            continue
        failures += report(f"{name} has_section", has, r["has_section"])
        failures += report(f"{name} marked", marked, r["marked"])
        failures += report(f"{name} solid", solid, r["solid"])
        failures += report(f"{name} code_material", code, r["code_material"])
    got = set(data.get("implement_alert", []))
    failures += report("implement_alert 集合全等", EXPECT_IMPL_ALERT, got)
    failures += report("docs-only 不进实现层警惕", False,
                       "distill-impl-docs" in got)
    print(f"\n{'实现层表全部通过' if failures == 0 else f'实现层表 {failures} 项不符预期'}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
