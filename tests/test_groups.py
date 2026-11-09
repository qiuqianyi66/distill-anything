#!/usr/bin/env python3
"""gate.py 五个分组函数的函数级单测（F4）。

为什么单独存在：`run_gate_tests.py` 走 subprocess 调 CLI，只能验「整份产物的最终三态」，
验不到某个分组函数单独改坏时的行为。加/改判据时想单独锁定一条，就在这里加断言。

每项都是「健康输入 → 该组 check 全 True」+「故意改坏 → 对应 check 翻 False」成对出现，
只有正向断言的单测在判据退化时仍然会绿（等于没有牙齿）。

用法：python tests/test_groups.py   （退出码 0 = 全过）
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gate  # noqa: E402

FAILS = []


def ctx_of(tmp, text, strict_anchor=False):
    """按 check() 的口径构造 _Ctx：同一份 text 同时喂 body / joined / fm，别自己拼。"""
    body, fm = gate.strip_code_and_frontmatter(text)
    target = Path(tmp) / "report.md"
    target.write_text(text, encoding="utf-8")
    return gate._Ctx(target, text, body, "\n".join(body), fm, strict_anchor)


def by_name(ctx, name):
    return [c for c in ctx.checks if c["name"] == name]


def expect(label, cond, detail=""):
    if not cond:
        FAILS.append(f"{label}: {detail}")
    print(f"{'ok  ' if cond else 'FAIL'} {label:<44} {detail}")


BASE_FM = """---
name: demo-report
description: 一句话说清用途
source: 本地实测
---
"""


def t_identity(tmp):
    """身份与骨架：frontmatter、三段必需节、fm-mangled。"""
    good = BASE_FM + """
# demo

## 5 证据台账
| 断言 | 层级 | 锚点 |
|---|---|---|
| a | [O] | E-11112222 |

## 6 诚实边界
- 只覆盖本地

## 7 未知台账
| 未知 | 为什么解不了 | 需要什么才能解 |
|---|---|---|
| b | 无权限 | 拿到权限 |
"""
    ctx = ctx_of(tmp, good)
    gate._check_identity(ctx)
    expect("identity:frontmatter 正常", by_name(ctx, "frontmatter")[0]["ok"] is True)
    expect("identity:三节齐备", all(by_name(ctx, f"section:{g}")[0]["ok"] is True
                                   for g in ("证据台账", "未知台账", "诚实边界")))

    broken = good.replace("## 6 诚实边界", "## 6 别的节")
    ctx = ctx_of(tmp, broken)
    gate._check_identity(ctx)
    expect("identity:缺诚实边界必须翻 False",
           by_name(ctx, "section:诚实边界")[0]["ok"] is False,
           by_name(ctx, "section:诚实边界")[0]["detail"])

    mangled = "***\nname: demo-report\ndescription: x\nsource: y\n***\n\n# demo\n"
    ctx = ctx_of(tmp, mangled)
    gate._check_identity(ctx)
    expect("identity:frontmatter 被改写要报 fm-mangled",
           any(c["ok"] is False for c in by_name(ctx, "fm-mangled")))


def t_evidence(tmp):
    """证据底座：标记数、锚点去重计数、严格锚点豁免。"""
    marks = "".join(f"- 观察{i} [O] E-{i:08x}\n" for i in range(1, 9))
    ctx = ctx_of(tmp, BASE_FM + "# demo\n" + marks)
    gate._check_evidence(ctx)
    expect("evidence:8 处标记成立", by_name(ctx, "markers")[0]["ok"] is True)
    expect("evidence:8 个不同 E id 锚点成立", by_name(ctx, "anchors")[0]["ok"] is True)
    expect("evidence:未开严格模式为 ok:None", by_name(ctx, "strict-anchor")[0]["ok"] is None)

    ctx = ctx_of(tmp, BASE_FM + "# demo\n- 观察但没标记\n")
    gate._check_evidence(ctx)
    expect("evidence:无标记必须翻 False", by_name(ctx, "markers")[0]["ok"] is False)

    # 重复锚点不凑数：同一个 E id 写 6 遍仍只有 1 处
    dup = "".join(f"- 观察{i} [O] E-aaaabbbb\n" for i in range(6))
    ctx = ctx_of(tmp, BASE_FM + "# demo\n" + dup)
    gate._check_evidence(ctx)
    expect("evidence:重复锚点不凑数", by_name(ctx, "anchors")[0]["ok"] is False,
           by_name(ctx, "anchors")[0]["detail"])


def t_conclusions(tmp):
    """结论质量：评价型裸结论、裸用断言词。"""
    bare = ("- 这个实现显然非常优秀，值得学习的地方很多\n"
            "- 这套流程毫无疑问是顶级水平，效果很好\n")
    ctx = ctx_of(tmp, BASE_FM + "# demo\n" + bare)
    gate._check_conclusions(ctx)
    expect("conclusions:评价型裸结论必须翻 False",
           by_name(ctx, "conclusions")[0]["ok"] is False, by_name(ctx, "conclusions")[0]["detail"])
    expect("conclusions:裸用断言词必须翻 False",
           by_name(ctx, "banned-words")[0]["ok"] is False)

    marked = "- 这个实现非常优秀，值得学习的地方很多 [O] E-ccccdddd\n"
    ctx = ctx_of(tmp, BASE_FM + "# demo\n" + marked)
    gate._check_conclusions(ctx)
    expect("conclusions:带标记后转 True", by_name(ctx, "conclusions")[0]["ok"] is True)
    expect("conclusions:带标记后断言词不再裸用", by_name(ctx, "banned-words")[0]["ok"] is True)


def t_references(tmp):
    """引用与存活：死链、锚点存活、未知台账深度。"""
    bad = BASE_FM + "# demo\n详见 references/not-exist.md:3\n"
    ctx = ctx_of(tmp, bad)
    gate._check_references(ctx)
    expect("references:死链必须翻 False", by_name(ctx, "refs")[0]["ok"] is False)

    ctx = ctx_of(tmp, BASE_FM + "# demo\n没有外部引用\n")
    gate._check_references(ctx)
    expect("references:无引用即全可达", by_name(ctx, "refs")[0]["ok"] is True)
    expect("references:无文件锚点时存活检查豁免", by_name(ctx, "anchor-liveness")[0]["ok"] is None)

    thin = (BASE_FM + "# demo\n\n## 7 未知台账\n| 未知 | 为什么解不了 | 需要什么才能解 |\n"
            "|---|---|---|\n| 某事 | 无权限 |  |\n")
    ctx = ctx_of(tmp, thin)
    gate._check_references(ctx)
    expect("references:未知台账缺「需要什么」必须翻 False",
           by_name(ctx, "unknown-depth")[0]["ok"] is False)


def t_size(tmp):
    """体积：只 warn 不判定。"""
    ctx = ctx_of(tmp, BASE_FM + "# demo\n短\n")
    gate._check_size(ctx)
    sc = by_name(ctx, "size")[0]
    expect("size:恒为 True（只 warn）", sc["ok"] is True, sc["detail"])
    expect("size:小文件不告警", sc.get("warn") is False)

    big = BASE_FM + "# demo\n" + ("填充行，用来把体积顶过告警线。\n" * 3000)
    ctx = ctx_of(tmp, big)
    gate._check_size(ctx)
    expect("size:超 60KB 只 warn 不改结论",
           by_name(ctx, "size")[0].get("warn") is True,
           by_name(ctx, "size")[0]["detail"])


def main():
    with tempfile.TemporaryDirectory() as td:
        for fn in (t_identity, t_evidence, t_conclusions, t_references, t_size):
            fn(td)
    print()
    if FAILS:
        print(f"{len(FAILS)} 项失败：")
        for f in FAILS:
            print("  " + f)
        return 1
    print("5 组 / 全项通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
