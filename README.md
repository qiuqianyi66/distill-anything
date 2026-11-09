<div align="center">

# distill-anything

**Turn any object — a person, a code repo, a long document, a skill library, an incident — into evidence-anchored, falsifiable, reusable knowledge.**

把任意对象压成「可证伪的判据 + 可追溯的证据 + 诚实的未知」，而不是又一篇摘要。

[![Stars](https://img.shields.io/github/stars/qiuqianyi66/distill-anything?logo=github&label=Stars)](https://github.com/qiuqianyi66/distill-anything/stargazers)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=fff)](#)
[![Tests](https://img.shields.io/badge/tests-29%20%2B%205%20groups-brightgreen)](#验收)
[![Version](https://img.shields.io/badge/skill-v1.1.9-blue)](SKILL.md)

**[它是什么](#它是什么) · [三层结构](#三层结构) · [快速开始](#快速开始) · [门禁](#门禁四态) · [判据](#判据什么叫蒸出来了) · [验收](#验收) · [边界](#诚实边界)**

</div>

> 这是个人方法论工具，不是通用框架。判据是我自己踩坑踩出来的，适用边界写在 `SKILL.md` 里，别当行业标准用。

---

## 它是什么

**蒸馏不是摘要。** 摘要压缩篇幅，蒸馏压缩不确定性：产出必须能回答「这条结论凭什么成立」「什么情况下它不成立」「还有哪些我根本不知道」。

这个技能做三件事：

1. **判据层**（`SKILL.md`）：七条「蒸出来了」的判据、九步流水线、八类对象的探针表、六条禁令。
2. **执行层**（`scripts/`）：机械动作全交给脚本——建骨架、存证据算指纹、批量校验、锚点收口、写入基线。
3. **状态层**（`evidence.jsonl` + `notes/`）：每条证据带原文指纹与行号，正文只引 id，文件一改门禁就知道。

判断标准统一成一句话：**删掉对象的名字，产物还得立得住。**

## 三层结构

```
distill-anything/
├── SKILL.md                 # 判据层：铁律 / 分诊 / 九步 / 判据 / 反模式
├── references/
│   ├── target-matrix.md     # 八类对象：首探针、必查三项、已知坑
│   ├── evidence-protocol.md # 三层标记、锚点格式、纠正流程
│   ├── quality-gate.md      # 门禁阈值 + 每次判据偏差的记录
│   └── templates/           # mechanism / perspective / rules 三型骨架
├── scripts/
│   ├── distill.py           # 执行层 CLI：init / gate / index / evidence / scan / stamp
│   ├── gate.py              # 单文件门禁，可独立调用
│   ├── anchorize.py         # 路径锚点批量换成证据 id
│   └── migrate_legacy.py    # 老产物迁进证据库
└── tests/
    ├── run_gate_tests.py    # CLI 级回归 29 例
    └── test_groups.py       # 五个分组函数的函数级单测
```

产物永远写到当前项目的 `out/distill-<slug>/`，不写进技能目录。

## 快速开始

```bash
# 1. 建骨架（三类产物型：mechanism / perspective / rules）
python scripts/distill.py init my-object --type mechanism

# 2. 读到关键段落就存一条证据：读原文、算指纹、追加一行
python scripts/distill.py evidence add \
  --dir out/distill-my-object --path raw/repo/SKILL.md \
  --lines 44-58 --level O --statement "入口只有这一处"

# 3. 正文里用 E-xxxxxxxx 引用，交付前过门禁
python scripts/gate.py out/distill-my-object/report.md
python scripts/distill.py gate out --recursive        # 整个 out 下所有产物
python scripts/distill.py scan --root out             # 只查锚点能不能解析
```

产物确认无误后建一次写入基线，之后文件被别的程序改写就会被抓出来：

```bash
python scripts/distill.py stamp out/distill-my-object/report.md
```

## 门禁四态

| 状态 | 含义 | 退出码 |
|---|---|---|
| `PASS` | 结构与证据达标 | 0 |
| `INCOMPLETE` | 证据段缺失、锚点未提供、stamp 之后被改写 | 2 |
| `FAIL` | 有结论无锚点、证据指向已失效、引用死链 | 1 |
| `SKIP` | 外来文件或中间件，判据不适用 | 0 |

`SKIP` 是刻意设计的：被蒸馏的原始现场（第三方技能、事故现场、`notes/`、`raw/`）本来就不声称结论，判它缺证据段是判据过度。识别走两条路径——frontmatter 带第三方技能键且缺 `source`，或目录里有 `.foreign` 标记。

## 判据：什么叫「蒸出来了」

1. 去名测试：删掉名字，产物还能被认出是谁。
2. 生成测试：拿它没谈过的新问题，能给出立场并说明理由。
3. 矛盾测试：至少留一对未被调和的矛盾。
4. 反模式测试：至少一条「它绝对不做什么」。
5. 未知测试：未知台账 ≥3 条，每条写明需要什么才能解。
6. 模型数测试（仅思维型）：心智模型落在 3–7 个。
7. 张力测试（仅思维型）：内在张力写成具体场景的两种相反选择。

## 验收

```bash
python tests/run_gate_tests.py   # 29/29
python tests/test_groups.py      # 5 组 / 全项通过
```

两个测试层互不替代：CLI 级验整份产物的最终三态，函数级直调五个 `_check_*` 分组函数。新增判据时两边都要能造红——只有正向断言的测试在判据退化时仍然是绿的。

## 诚实边界

- 判据来自我自己的踩坑记录，不是行业标准；`references/quality-gate.md` 里每次偏差都留了日期和原因。
- 跨版本不保证：门禁对历史产物有一批 `ok:None` 的豁免（无证据库、无写入基线、锚点未 E 化），这些是「不惩罚历史」，不是「已通过」。
- 八类对象里只有「代码仓库」做过第二样本，其余七类仍单例，判据在那七类上成立与否没有独立证据。
- 二十四条未知台账留着，全是本地解不了的（跨会话对比、真实运行、目标客户端 tokenizer、联网核实原文）。
