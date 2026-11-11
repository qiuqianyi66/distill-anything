<div align="center">

# distill-anything

**Evidence-based knowledge distillation for AI agents and LLMs — turn any person, code repo, long document, skill library, incident, or methodology into evidence-anchored, falsifiable, reusable knowledge.**

把任意对象压成「可证伪的判据 + 可追溯的证据 + 诚实的未知」，而不是又一篇摘要。
An open-source distillation skill + CLI with a four-state quality gate (PASS / INCOMPLETE / FAIL / SKIP), built for AI agent / LLM workflows, Claude-style skills, and reverse engineering.

[![Stars](https://img.shields.io/github/stars/qiuqianyi66/distill-anything?logo=github&label=Stars)](https://github.com/qiuqianyi66/distill-anything/stargazers)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=fff)](#)
[![Tests](https://img.shields.io/badge/tests-44%20%2B%205%20groups-brightgreen)](#验收)
[![Version](https://img.shields.io/badge/skill-v1.1.30-blue)](SKILL.md)
[![License](https://img.shields.io/github/license/qiuqianyi66/distill-anything)](#)

**[示例作品](examples/README.md) · [它是什么](#它是什么) · [三层结构](#三层结构) · [快速开始](#快速开始) · [门禁四态](#门禁四态) · [运行安全](#运行安全) · [判据](#判据什么叫蒸出来了) · [验收](#验收) · [边界](#诚实边界)**

</div>

> 个人方法论工具，不是通用框架。判据来自真实踩坑，适用边界写在 `SKILL.md`，别当行业标准用。

---

## 它是什么

**蒸馏不是摘要（distillation ≠ summarization）。** 摘要压缩篇幅，蒸馏压缩不确定性：每条结论必须能回答「凭什么成立」「什么情况下不成立」「还有哪些不知道」。

适用于八类对象：代码仓库、人物、长文档、技能库、事故、对话日志、竞品、方法论流派。这个技能做三件事：

1. **判据层**（`SKILL.md`）：「蒸出来了」的判据、流水线、八类对象探针、行为禁令。
2. **执行层**（`scripts/`）：机械动作全交给脚本——建骨架、存证据算指纹、批量校验、锚点收口、写入基线、盲化评分。
3. **状态层**（`evidence.jsonl` + `notes/`）：每条证据带原文指纹与行号，正文只引 id，文件一改门禁就知道。

核心判断标准：**删掉对象的名字，产物还得立得住。** 关键词：knowledge distillation、evidence protocol、falsifiable claims、AI agent skill、LLM reliability。

> 想看真实成品：[`examples/`](examples/README.md) 含两份脱敏后的蒸馏作品（rules + mechanism），每条结论都挂着可核验的证据 id。

## 三层结构

```
distill-anything/
├── SKILL.md                 # 判据层：铁律 / 分诊 / 流水线 / 判据 / 反模式
├── references/
│   ├── target-matrix.md     # 八类对象：首探针、必查项、已知坑
│   ├── evidence-protocol.md # 三层标记、锚点格式、外部来源分级、纠正流程
│   ├── quality-gate.md      # 门禁阈值 + 每次判据偏差的留痕
│   └── templates/           # mechanism / perspective / rules / refuse 四型骨架
├── scripts/
│   ├── distill.py           # 执行层 CLI：init/gate/index/evidence/scan/stamp
│   ├── gate.py              # 单文件门禁，可独立调用
│   ├── anchorize.py         # 路径锚点批量换成证据 id
│   ├── d7_blind.py          # 盲化评分，防自由打分
│   └── migrate_legacy.py    # 老产物迁进证据库
└── tests/
    ├── run_gate_tests.py    # CLI 级回归 44 例
    └── test_groups.py       # 五个分组函数的函数级单测
```

产物永远写到当前项目的 `out/distill-<slug>/`，不写进技能目录。

## 快速开始

```bash
# 1. 建骨架（mechanism / perspective / rules / refuse）
python scripts/distill.py init my-object --type mechanism

# 2. 读到关键段落就存一条证据：读原文、算指纹、追加一行
python scripts/distill.py evidence add \
  --dir out/distill-my-object --path raw/repo/SKILL.md \
  --lines 44-58 --level O --statement "入口只有这一处"

# 3. 正文用 E-xxxxxxxx 引用，交付前过门禁
python scripts/gate.py out/distill-my-object/report.md
python scripts/distill.py gate out --recursive        # 整个 out 下所有产物
python scripts/distill.py scan --root out             # 只查锚点能不能解析
```

确认无误后建写入基线，之后文件被别的程序改写就会被抓出来：

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

`SKIP` 是刻意设计：被蒸馏的原始现场（第三方技能、事故现场、`notes/`、`raw/`）本就不声称结论，判它缺证据段是判据过度。识别走两条路径——frontmatter 带第三方技能键且缺 `source`，或目录里有 `.foreign` 标记。

## 运行安全

非 refuse 产物必须同时覆盖三类语义，缺任一类即 INCOMPLETE：

1. **失败显式**：错误分可重试/永久失败，禁止静默报成功，错误码显式返回。
2. **危险操作确认**：删除等危险动作二次确认，写操作显式选择加入（opt-in / confirm）。
3. **资源释放**：子进程、浏览器、句柄用后即释放，teardown 统一清理，防资源泄漏。

来源：真实 GitHub issue 层对照——多个高 star 项目栽在「文档/状态与真实实现脱节」（静默成功、危险操作无确认、资源不释放）。

## 判据：什么叫「蒸出来了」

1. 去名测试：删掉名字，产物还能被认出。
2. 生成测试：拿没谈过的新问题，能给出立场并说明理由。
3. 矛盾测试：至少留一对未被调和的矛盾。
4. 反模式测试：至少一条「它绝对不做什么」。
5. 未知测试：未知台账 ≥3 条，每条写明需要什么才能解。
6. 模型数测试（仅思维型）：心智模型落在 3–7 个。
7. 张力测试（仅思维型）：内在张力写成具体场景的两种相反选择。
8. 降级测试：必须写明失败时退到哪（触发 → 一线修复 → 仍失败兜底）。

## 验收

```bash
python tests/run_gate_tests.py   # 44/44
python tests/test_groups.py      # 5 组 / 全项通过
```

两个测试层互不替代：CLI 级验整份产物的最终状态，函数级直调五个 `_check_*` 分组函数。新增判据时同提交必须给一个能打红的反例——只有正向断言的测试在判据退化时仍然是绿的。

## 诚实边界

- 判据来自真实踩坑，不是行业标准；`references/quality-gate.md` 每次偏差都留了日期和原因。
- 跨版本不保证：门禁对历史产物有一批 `ok:None` 的豁免（无证据库、无写入基线、锚点未 E 化），这是「不惩罚历史」，不是「已通过」。
- 证据 id 作用域＝容器：跨容器 id 可能相同但只在本容器解析，当前无跨容器引用，全局聚合时才需引入 slug。
- 只判结构，判不了「锚点是否指向真实成立的内容」；PDF/图片/表格类产物需人工核对。
