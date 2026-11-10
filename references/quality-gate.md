# 质量门禁

## 用途

`scripts/gate.py` 检查**蒸馏产物**（`out/distill-<slug>/` 里的 SKILL.md / report.md），不检查技能说明文档本身。它只判结构，不判结论真假——真假由三重验证（SKILL.md S6）负责，两者不可互相替代。

```bash
python scripts/distill.py gate <产物路径...>   # 推荐入口，支持多文件汇总
python scripts/distill.py gate <产物...> --strict-anchor   # 交付前必跑：E id 占锚点 ≥50%
python scripts/gate.py <产物路径> --json        # 单文件 JSON
python scripts/distill.py index --root out      # 校验证据库（stale/dead/悬空引用）
python tests/run_gate_tests.py                 # 回归（改判据后必跑）
```

## 三态语义（GAP 与 VIOLATION 必须分开）

| 状态 | 退出码 | 含义 | 处置 |
|---|---|---|---|
| PASS | 0 | 结构与证据达标 | 交付 |
| INCOMPLETE | 2 | 证据**还没提供**（GAP） | 继续采集，不算失败 |
| FAIL | 1 | 给了结论但**没有证据**（VIOLATION） | 补锚点或删结论 |

把两者合成一个「红」，会造成两种伤害：一是历史草稿永久假红，二是真正的裸结论被当成「还没写」而混过去。所以输出里 GAP 与 VIOLATION 分列，修复建议也分开给。

## 阈值

| 检查 | 阈值 | 类型 |
|---|---|---|
| frontmatter 含 name + description | 硬性；report 型无 frontmatter 记 GAP 不记违规 | GAP |
| 必需段：证据台账 / 未知台账 / 诚实边界 | 三选三，缺一记 GAP | GAP |
| 三层标记 `[O]/[D]/[I]` | ≥ 8 处 | GAP |
| **锚点（`路径:行` / URL / `E-xxxx`）** | ≥ 5 处，**按去重后的不同锚点计数** | GAP |
| **E id 占比（`--strict-anchor`）** | ≥ 50%，仅对有证据库且 ≥5 条的产物生效 | GAP |
| 评价型裸结论 | ≥ 2 条直接 FAIL | VIOLATION |
| 未标记结论比例 | > 40% 且结论 ≥ 5 条且基础证据已达标 → FAIL | VIOLATION |
| 裸用断言词（显然/众所周知/据说是…） | 命中即 FAIL | VIOLATION |
| 引用 `references/*.md` | 文件必须存在，缺一即 FAIL | VIOLATION |
| **锚点存活**（抽样 20%，至少 3 处） | 文件须存在、行号须在范围内；同名文件行段内容不同即判「歧义」FAIL | VIOLATION |
| **锚点越界** | `../` 或绝对路径一律不可解析；解析结果必须落在产物目录内 | VIOLATION |
| **相对链接 / `#锚点`** | 链接目标须存在；`#锚点` 须在目标文档里找到归一化后的同名标题（去#、去标点、转小写、空格转-） | VIOLATION |
| **证据 id `E-xxxx`** | 须在最近一层 `evidence.jsonl` 中；缺失 FAIL，内容已变 GAP | VIOLATION / GAP |
| **未知台账深度** | 每行必须填「需要什么才能解」，缺一记 GAP | GAP |
| 体积 | > 60KB 仅告警，不拦 | WARN |

锚点存活与证据 id 是 v1.1 新增的两道硬校验。此前门禁只匹配「路径:数字」的字形，从不验证文件是否存在——写一条 `foo/bar.md:999` 也能通过，等于一个从不验证证据的证据门禁。现在：

- `路径:行` 走**抽样**（确定性哈希抽样，不是随机，保证回归可复现），避免全量读几千个文件。
- `E-xxxx` 走**指纹**：条目声称的原文片段变了就转 `changed`。
- 同名文件（多个 raw 仓库都有 `README.md`）行段内容不同时判 `歧义`，要求写全相对路径（如 `raw/agent-browser/README.md:44`）。机器不猜你指哪个仓库。

`结论行`的定义：bullet（`-` `*` 数字序号）、非表格、非标题、长度 ≥15 字。代码块与 frontmatter 内的内容不计入，避免把示例当证据。

**锚点按「节」绑定，不按行**：一条机制的四个字段（解决什么/实现要点/前置条件/证据）共用一条证据是正常写法，逐行要求会逼出重复锚点噪音。所在 `###` 节内只要有 ≥1 处锚点，节内 bullet 视为已锚定；整节无锚点才算裸结论。这条判据来自 security-audit 的 finding+trace 结构（一个结论带一条 trace 数组，不是每句一个）。

**豁免节**：标题含「诚实边界 / 局限 / 未知 / 反模式 / 不搬」的节，其内条目本来就不声称事实，不参与裸结论统计。若把这些也计入，任何诚实的产物都会被判红。

**不进门的文件**：`notes/` 与 `raw/` 下都是中间件（候选台账、原始素材），不声称结论。`distill.py gate` 遇到它们直接打印 `[SKIP]` 并跳过判定——对它报 INCOMPLETE 会把中间件当成品，属「判据过度」。

评价型裸结论 = 无任何标记/锚点，且含「优秀/很强/明显高于/值得推荐/没有之一/应该是/顶级/完美」这类不可证伪的评价词。纯结构性描述（「本章分三节」）不算违规，只记 GAP。

## 反例验证（本版实测，2026-11-07）

| fixture | 预期 | 实测 | 退出码 |
|---|---|---|---|
| `good.md` | PASS | PASS（10 标记 / 17 文件锚点 + 1 URL / 2 条未标记结论未超限） | 0 |
| `bad.md` | FAIL | FAIL（4 条评价型裸结论被点名） | 1 |
| `incomplete.md` | INCOMPLETE | INCOMPLETE（缺三段落 + 0 标记 + 0 锚点，全部记 GAP） | 2 |
| `missing-ref.md` | FAIL | FAIL（引用 `references/not-exists.md` 不存在） | 1 |

调前端两版都出过偏差，记在这里防复发：
1. 首版把「有锚点但一批裸结论」判成 INCOMPLETE —— 违规被归成缺失。
2. 第二版把「任意 1 条未标记结论」记 GAP —— 达标产物被拖成 INCOMPLETE，假红。
3. 第三版（首次跑真实对象时）对四份真产物全报 FAIL —— 逐行绑定锚点，把「一条机制共用一条证据」和「诚实边界条目」都算成裸结论。改为节级绑定 + 豁免节后，四份真产物 3 份 PASS、1 份因缺锚点 GAP（补真实锚点后 PASS）。
现在的判据是：**评价型裸结论独立触发 FAIL；结构性缺标记只在 ≥3 条且占比 >30% 时记 GAP；锚点与技术性判断按节绑定；边界类条目豁免。**

## 真实产物验证（2026-11-07，GitHub Trending 前三）

| 产物 | 结果 | 说明 |
|---|---|---|
| `deep/security-audit-skill.md` | PASS | 14 标记 / 18 文件锚点 / 3 节待补 |
| `shallow/agent-browser.md` | PASS | 8 标记 / 8 锚点 |
| `shallow/google-skills.md` | 首轮 GAP → 补锚点后 PASS | 差异 1 个锚点，暴露「条目式锚点无行号不算锚点」 |
| `REPORT.md` | 首轮 FAIL → 改写后 PASS | 自检节的 4 条叙述被当结论，合并成段落后通过 |

这轮的价值不在「通过」，而在三次假红都指向判据本身：**门禁必须能区分「证据缺失」「结论无据」「不声称事实的条目」三类，否则越严越假。**

## 第二类对象验证（2026-11-08，长文档 / rules 型）

对象：`docs/plans/skill-callability-r2.md` v9（640 行 / 26.8KB 字符，非代码仓库）。产物：`out/distill-skill-callability/report.md`（10 条判据，19 条证据，`source_ref=file:sha256:9a457cdb`）。

| 检查 | 结果 |
|---|---|
| 首轮 `distill gate` | PASS（退出码 0，未做任何修补） |
| `migrate_legacy` 抽证据 | 19 条，0 跳过（首轮有 1 处假锚点，改写后归零） |
| `distill index` | 19 条证据 / 1 份产物 / 引用 17 个，退出码 0 |
| `distill scan --root out` | 2 个目录 / 43 处锚点 / 0 问题 |

同一天 `index` 对 trending 目录的引用数从 6 涨到 20，说明路径锚点反查生效：**同一处证据用 `路径:行` 或 `E-xxxx` 写，现在都计入 supports。**

已知遗留（未修，不在本轮范围）：trending 产物里 `E-9d9e9838` 与 `E-415abd3b` 标为 `[D]` 但只挂单个锚点，违反「[D] 至少两处合成」；修它要改产物正文，而本轮红线是不改正文，登记待下一轮。



## 判据修正记录（v1.1，2026-11-07 ~ 11-08）

| 日期 | 现象 | 根因 | 改法 |
|---|---|---|---|
| 11-07 | 4 份真实产物全 FAIL | 锚点逐行绑定 | 按 `###` 节绑定 + 豁免诚实边界/未知/反模式节 |
| 11-07 | fixture `good.md` 的虚拟路径不可解析 | 判据只验字形，从不验存在性 | 补 7 个真实样例文件 + 新增 anchor-liveness |
| 11-07 | 迁移出的 20 条里两条指向错误 | ① 正则不支持行段，`14-17` 截成 `14`；② 同名 `README.md` 取任一副本 | 正则加 `(?:-\d+)?`；同名文件行段内容不同即判歧义，产物改全路径 |
| 11-08 | 纯 E 引用产物报「锚点不足」 | E id 未计入 `anchor_total`，与 SKILL 的「两种写法」矛盾 | 三种写法等价计数；`_marked` / 断言词检查同步认 E id |
| 11-08 | dead 证据被报成「内容已变，需重读改断言」 | `evidence_state()[0] != "ok"` 把 dead 与 changed 合并 | dead → VIOLATION（指向失效），changed → GAP（需重读） |
| 11-08 | 中间件 `notes/candidates.md` 被判 INCOMPLETE（缺 frontmatter / 未知台账 / 标记 / 锚点） | 把候选台账当成品判；判据过度 | `distill gate` 对 `notes/`、`raw/` 直接 `[SKIP]`，不参与汇总 |
| 11-08 | 路径锚点产物 `index` 后 `supports` 全空、引用 0 个 | `index` 只按 `E-xxxx` 统计，与 SKILL「两种写法等价」矛盾 | 新增 `resolve_anchor_path`，按 (path, lines) 反查证据 id，路径锚点等同引用 |
| 11-08 | 迁移把正文里当例子写的 `foo/bar.md:999` 收成了证据 | 例子与真锚点字形无差别 | 未修判据，产物改写为「超过文件长度的行号」；已登记为静默失效点 |
| 11-08 | 40 条证据里 22 条 `statement` 是机械残渣（「证据： ；」「1 \| 要…」「… / O」） | `clean()` 只去边缘 `\|`，表格整行进 statement；尾部「证据」被一概删除，连「自述不构成证据」也砍 | 表格按单元格合并并丢序号/层级列；尾部只删「… \| 证据」形态；重跑后两目录 39 条可疑数为 0 |
| 11-08 | 某产物报「8 个锚点」却只有 4 处不同 | `anchor_total` 用 list 长度（含重复），同一锚点重复可凑够 ≥5 | 改去重计数；该产物当场从假绿转红，补 3 条真实证据后转绿 |
| 11-08 | 两条 `[D]` 只挂单锚点，第二处写的是「本库某某规则」 | 证据库混进了**映射结论**，与原文事实共用同一行段，变成两条同名证据 | 证据库只存原文事实；这两条降为 `[I]` 并删掉冗余条目。判据：映射/推导不进 `evidence.jsonl` |
| 11-08 | 锚点写 `../../../Windows/win.ini:1` 能解析成功 | 拼路径时没做目录边界校验，门禁可拿产物外的任意文件充证据 | 加 `_inside()` 与绝对路径拒绝，越界判不可解析；新增回归 `anchor-escape` |
| 11-08 | 产物在讲「该怎么检测假引用」，自己却因写了 `references/xxx.md` 被门禁判 FAIL | references 检查按字面匹配，不区分代码块与示例 | 未改判据，产物改写为不含路径字面的表述；已在诚实边界登记为判据局限 |
| 11-08 | `init --type rules` 产出的却是 mechanism 骨架（结构地图 / 关键决策） | `cmd_init` 从来没读 `args.type`，三型共用一份 `SKELETON`，参数只做了校验 | 拆成 `SKELETONS[type]` 三份骨架；新增 3 例回归 `init-skeleton-*`；反例注入（把 rules 指回 mechanism）实测 18/19 退出 1，还原后 19/19 退出 0 |
| 11-08 | 读者点开产物里的相对链接会 404 | 门禁只查 `references/*.md` 存在，没查一般相对链接与 `#锚点` | 新增 links 检查（`← skill-callability-r2 §4.8 F6` 的 LINK-404 / ANCHOR-404），代码块内不查 |
| 11-08 | `distill gate --json` 的 stdout 后面还跟着 `summary:` 与 `[SKIP]` 行，管道 `json.loads` 报 Additional text encountered | `--json` 只切了主体输出，收尾的人类可读行照旧走 stdout | summary 与 `[SKIP]` 在 `--json` 时改走 stderr；新增回归 `json-gate-stdout` |
| 11-08 | 规则型产物的「假阳性排除 / 根因层 / 防复发门禁」三节无锚点，被判 6/12 条结论未标记 | 结论检查按节绑定，连不声称事实的段落也计入分母 | 未改判据，给三节补真实锚点后 PASS（11 份产物全绿） |
| 11-08 | 思维型产物的「心智模型 3-7 个」「至少 1 对内在张力」两条规则只写在 SKILL 里，gate 一句不验；实测 nuwa 成品加 8 个模型仍判绿 | 规则与判据脱节：写了没实现等于没有 | 新增 `persp:models` / `persp:tension` / `persp:agentic` 三项，**只对「name 以 -perspective 结尾」或「有『心智模型』标题节」的产物生效**；超上限=VIOLATION，不足与缺张力=GAP，agentic 缺失先记 `ok:None` 提示不拦，观察一轮 |
| 11-08 | 首版 `persp:tension` 对芒格成品判「无内在张力」，实际它有 4 条 | 张力条目用的是 `1. 2. 3.` 有序列表，判据只认 `- ` 与 `* ` 两种 bullet | 条目写法改为 `[-*]` 与 `\d+[.)]` 等价；另认「张力写在节内粗体子标题下」的合法写法（steve-jobs 就是 `**我自己也没想清楚的**（内在张力）：`），但限定行首须是 `**` 或 `#`，避免正文随口提「张力」误计数 |
| 11-08 | 同一判据第二轮：`distill-method-schools` 与 `distill-user-thinking` 两份真实产物被判「0 个心智模型、无张力」 | 模型编号写成 `### M1`，张力写成 4 行**表格**——判据只认数字编号与 bullet | 模型认 `### (模型\|M)?数字`；张力再补表格形态（表头不算条目、分隔行排除）。**同一判据栽两次，说明「等价写法必须穷举」不是一次性的事**：每新增一条判据，先拿全库已有产物跑一遍，比自造 fixture 更能暴露写法差异 |
| 11-08 | 产物写入后被 markdown 格式化器重写：frontmatter 的 `---` 变成 `***`、`_ref` 变成 `\_ref`、`- ` 变 `* ` | 环境对 .md 做了二次渲染回写，不是产物自身内容 | 修复 frontmatter 与转义后 gate 转 PASS。**教训：产物落盘后必须复跑 gate，不能只看写入时的返回**——写入成功不等于文件内容仍是写进去的那份 |
| 11-08 | 被改写后的产物 gate 报的却是「缺 frontmatter（若为 report.md 可豁免）」，被当成一张温和的提示放过 | `strip_code_and_frontmatter` 只认首行 `---`，`***` 时 fm 为空，于是「文件损坏」被误判成「本来就没有 frontmatter」——比漏检更糟的假绿 | 新增 `fm-mangled`：首行不是 `---` 但随后 12 行内出现 YAML 键 → 直接 VIOLATION 并给修复指令。反例注入：禁用该检查后同一 fixture 由 `FAIL(exit 1)` 退化成 `INCOMPLETE(exit 2)`，正是要防的降级 |

回归覆盖：`tests/run_gate_tests.py` **24/24** —— 4 份产物格式（PASS/FAIL/INCOMPLETE/FAIL）+ 6 种证据库状态（成立 / 失效 / 已变 / 无库 / 路径锚点等价 / 老化）+ 3 例严格锚点（未 E 化 / 收口后 / 重复不凑数）+ 1 例越界锚点 + 2 例链接（可达 / 404）+ 3 例 `init --type` 骨架区分 + 1 例 `--json` stdout 纯净 + **3 例 perspective 结构**（5 模型+张力应过 / 8 模型应红 / 缺张力应 INCOMPLETE）+ **1 例 frontmatter 被改写**（`fm-mangled` 必须 FAIL）。

perspective 三项的反例注入：把 `MAX_MODELS` 由 7 改成 20，`persp-models-8` 当场由 FAIL 转 PASS（22/23），还原后回到 FAIL（23/23）——证明这三项是被该常量驱动的真判据，不是死代码。四个真实样本（munger / steve-jobs / sun-yuchen / x-mastery）实测：前三份三项全绿，x-mastery 作为主题型产物未触发（它没有「心智模型」标题节）。

### v1.2（2026-11-08）严格锚点开关

`--strict-anchor` 默认关。开启时要求正文 E id 占锚点总数 ≥50%，**只对「有 `evidence.jsonl` 且证据 ≥5 条」的产物生效**——不加这条豁免，5 份老产物会集体假红，判据就变成了「惩罚历史」。

| 实测 | 结果 |
|---|---|
| 未 E 化的新产物（24 处锚点里 0 处 id） | INCOMPLETE，退出 2 |
| 同一份收口后 | PASS，退出 0（17 处 id / 7 处指路） |
| 证据库只有 3 条的 fixture | 豁免 `ok:None`，仍 PASS |

配套 `scripts/anchorize.py`：只把**带 `[O]/[D]/[I]` 标记的行**里的路径锚点换成 id，「待补读某文件某行」这类指路不动。两个目录实测替换 17 + 26 处、新增证据 0 条（库里本来就有对应条目，说明之前的 `evidence add` 没有漏收）。

收口后 `index` 引用数不变（新产物 17、trending 23），说明反查与直接引用在同一口径上。

### v1.3（2026-11-08）锚点边界与压测

锚点只允许落在产物目录内。`../`、`C:/` 这类写法以前能解析成功（等于门禁替你去读任意系统文件），现在直接判「锚点越界」。

压力实测（同一台机器，含解释器启动）：

| 场景 | 结果 |
|---|---|
| 300 处不同锚点 / 300 行原文 | 152ms，PASS，抽样 60/300 全部成立 |
| 同 fixture 加 `--strict-anchor` | INCOMPLETE，退出 2，报「E id 0/300 = 0%」 |
| 真实 6 份产物 | 130ms 量级，全 PASS |

`index` 与 `scan` 都支持 `--json`（`scan --json` 只输出 JSON，不混人类可读行，方便管道解析）。

实测耗时（Windows / PowerShell，含解释器启动）：`distill gate` 五份 131ms，`distill index` 19 条 139ms，`distill scan` 43 处锚点 328ms。

## 怎么改红 / 改绿

- 想确认门禁真的会红：删掉产物里所有 `[O]/[D]/[I]`，或加一条「这个项目非常优秀值得学习」，必须 FAIL。
- 想让产物变绿：给结论补真实锚点，删掉无法锚定的评价句。**禁止**为了过门禁把锚点写成站点根、搜索页或臆造路径。
- 改阈值 = 改判据，必须同步改本文件并重跑 `tests/run_gate_tests.py`，否则下一个人无法判断是产物退化了还是门禁放宽了。

## 已观察未加齿：降级路径（2026-11-09）

`section:降级路径` 只看字形（兜底 / fallback / 降级 / 失败模式），**只记不建议，不改变三态**。

- 为什么先不加齿：实测 14 份产物里 6 份没有这一节。直接升成必需段 = 一次性把 6 份历史产物判红，等于惩罚历史，与「判据过度先豁免观察一轮」的纪律冲突。
- 补齐进度（2026-11-09）：**14 份产物全部具备**该节（gate 实测 14/14）。最后一批补的是 trending 那三份子报告与 REPORT（边界失效兜底 3 条 / 只读到 README 层兜底 3 条 / 榜单失效兜底 5 条），此前补的 `distill-user-thinking`、`distill-distilly-repo` 各 5 条、`distill-method-schools` 与 `distill-nuwa-method` 原有。
- **是否升硬判：暂不升，理由与代价已量化**。产物侧条件已满足，但一旦升为必需段，`tests/fixtures` 里 **13 个样例全部要加兜底段**（现在一个都没有），`fallback-soft` 守卫也要反过来重写；那是把一次判据升级变成一次 fixture 重构，收益（多拦一类缺失）小于风险（改写样例会动到每条判据的既有语境）。留作待拍板项，需要时按「先加守卫反例、再改判据、最后批量补样例」三步走。
- 依据：SkillLens 三元件之一 failure-mechanism encoding；达尔文的五 judge 对照里「边界条件覆盖」「检查点设计」是劣化最猛的两维（-5.8 / -6.4），说明这一节确实是质量杠杆而不是装饰。
- 升级条件：等剩下的口径也定下来（子报告各自补 or 明确由 REPORT 统一承载）后，再考虑升为必需段；升级时必须先让回归变红（`fallback-soft` 这例就是防止有人偷偷把它改成硬判的守卫）。
- 回归：`tests/run_gate_tests.py` 的 `fallback-soft` 断言「无兜底词的 good.md 仍 PASS 且该 check 的 ok 为 None」。

## 判据牙齿审计（2026-11-09）

来源：ponytail 的做法是「每条判据自带 good/bad 两份实现，selftest 断言打分器分别给 1 和 0」。搬过来的最小版本是**扫出「从未被判红过」的判据**，再逐条补反例。

- 工具：`scripts/teeth_audit.py`（只读，跑全部 fixture + 汇总每条 check 的 True/False/None 分布；`python scripts/teeth_audit.py` 即可）。
- 审计结果：21 条判据里 9 条从未在 fixture 上判红。逐条分诊后——
  - **真没牙齿，已补 3 例**：`banned-words`（新增 `banned-word.md` → FAIL）、`unknown-depth`（`unknown-thin.md` → INCOMPLETE）、`frontmatter` 的不完整分支（`fm-partial.md` → INCOMPLETE）。回归 30 → **33/33**。
  - **fixture 里没红，但 main() 里有动态用例**：`links`（LINK-404 → FAIL）、`strict-anchor`（未 E 化 → INCOMPLETE，收口后 → PASS）、`write-integrity`（stamp 后篡改 → GAP）。这三条不算无齿，只是不在 fixture 目录里。
  - **有意无齿**：`size` 只带 `warn` 标记、不改变三态（体积大不等于不合格，只提示）；`persp:agentic` 与 `section:降级路径` 是观察期判据，ok 恒为 None 或 True。
- 纪律：新增任何判据，必须在同一次提交里给出一个能把它打红的用例；否则它只是一句愿望。

## 从「验形态」到「验行为」：集合断言四例（2026-11-09）

上一轮只问「这条判据红过没有」，这一轮问的是「红的理由是不是它」——前者只能证明判据会响，证明不了响的原因。

- **归因字段本来就有**，不需要给 gate 加输出：`checks[]` 每项都带 `name / ok / kind`，判红的集合就是 `{c.name for c in checks if c.ok is False}`。本轮唯一要补的是**断言口径**，不是字段。
- **口径改为集合全等**：`fired == 预期集合`。只断言「预期名 in fired」会把「被别的判据顺带拦下」也算通过，等于假验收。
- 新增 4 个变异夹具（每条只种一处缺陷），并把「反向验证」写进同一条用例：把对应判据临时放宽（`MARK_MIN=0` / `ANCHOR_MIN=0` / `resolve_anchor` 恒真），该夹具必须转 PASS，否则说明它红在别的理由上。

| 夹具 | 缺陷 | 预期状态 | 预期 fired | 临时放宽谁 → 应转 PASS |
|---|---|---|---|---|
| `mut-anchor-range.md` | 锚点行号越界（`src/core.ts:3` → `:9999`） | FAIL | `{anchor-liveness}` | `resolve_anchor` |
| `mut-anchor-outside.md` | 锚点指向容器外（`../../outside.md:5`） | FAIL | `{anchor-liveness}` | `resolve_anchor` |
| `mut-marker-count.md` | 标记清零（20 → 0） | INCOMPLETE | `{markers}` | `MARK_MIN=0` |
| `mut-anchor-count.md` | 锚点压到 4（文件 4 + URL 0） | INCOMPLETE | `{anchors}` | `ANCHOR_MIN=0` |

- 回归：33 → **37/37**。
- **两条实测教训，写作时别踩**：① `anchors` 统计的是「文件 + URL + 证据 id」**总数**，只删文件锚点、留着 URL 时仍可能达标（4+1=5 就过）；② `anchor-liveness` 是**确定性抽样**（≤3 全查，否则按 sha1 取 20%、至少 3），破坏一个锚点未必被抽到——所以夹具要么把锚点数压到 ≤3，要么接受「抽样命中率」这个先天不确定性，不能据此说「这条判据必红」。
- 软化措辞（可以考虑 / 也许 / 根据情况）**不在 gate 里**，只有 `score_product.py` 的 D5 扣分；别把它当成门禁判据写进表里。

## D7（生成力）的盲化标定（2026-11-09）

判据与方法：`references/d7-blind-protocol.md`；工具：`scripts/d7_blind.py`（plan / score / report，`--reveal` 才看映射）。

- 做法：先把 5 条判据（给立场 / 给做法 / 给依据 / 给边界 / 不失真）写定，再遮蔽臂标签、每轮重新打乱、内联正文，评完揭盲。
- 结论口径已降级：**只报「三轮多数 + 一致/分歧」，不报分差与置信区间**——单人三轮撑不起区间，报出来是装饰。
- pilot（1 个问题 × 4 臂 × 3 轮，n=1）：产物最好 5 分 vs 空臂 3 分（差 2，可区分）；三派之间 5 vs 4（差 1，不可区分）。详见 `runtime/out/skills-governance/distill-cross-compare/notes/d7-blind-pilot.md`。
- 已知污染：评审者就是产物作者。遮蔽压得住「记得出处」，压不住「记得自己写过什么」，所以这只是标定，不是结论。
- **扩样（2026-11-10）**：5 问题 × 4 臂 × **独立评审者**（评者只看匿名文本，禁止打开映射）。均值：darwin 4.2 / 现行流程 4.0 / DisCo 3.6 / 空臂 2.4 → 产物 vs 空臂差 1.6（可区分），三派之间差 ≤0.6（不可区分）。同一批文本自评比独立评审高 1–2 分，差额集中在「边界」一条：**作者看得见自己的边界，别人看不见**。结论：D7 只能横向比「有方法 vs 没方法」，不能给流派排名。详见 untime/out/skills-governance/distill-cross-compare/notes/d7-blind-5q.md。

## 掏空探针：哪些门只认排版（2026-11-10）

搬自 ronce-racine `docs/evaluating-skills.md` 的 `eval:probe`：它拿一份「标题齐全、内容为零」的交付物去过门，
凡是还能过的门就是格式门；作者用这个数把 58 条门里的 43 条格式门清到 4 条。

我方对应实现 `scripts/gate_probe.py`（只读，不改任何产物）：按结构保留（frontmatter/标题/表格表头）、
内容全掏空（单元格清空、正文换成空 bullet、标记与锚点全部去掉），再用同一套 gate 判。

- 结果（18 份产物）：**掏空后没有一份 PASS**（说明结构本身过不了门），但通过项里 **126 条是格式门、117 条验内容（格式占比 52%）**。
- 减去修掉的假阳性后的变化曲线：71% → 59% → 52%。两次下降都不是「把门放宽」，而是把**假装验过**的检查改成「没东西可验就不报 True」：
  - `conclusions` 在零结论时曾报 `0/0 未标记`（空集真值）→ 改 `ok=None`；
  - `refs` 在零引用时曾报「全部可达」→ 改 `ok=None`；
  - `links` 在零相对链接时曾报「全部可达」→ 改 `ok=None`；
  - `write-integrity` 在「容器有基线、这张产物没有 stamp 记录」时曾报「与基线一致」——**这是最危险的一条：把没验过说成验过**，已改 `ok=None`。
- 剩下 126 条格式门里，`section:*` / `frontmatter` / `size` 是设计上的结构判据（本来就该只看排版），`banned-words` 是禁令类（空文档不违规是真话）。真正该被质疑的格式门已经清零。
- 纪律：新增判据时必须自问一句「把内容掏空，它还过不过」；过，就说明它验的是排版，得在 `references/quality-gate.md` 里写明理由，否则不要加。
- 口径提醒：`gate_probe.py --recursive` 自己按「父目录名以 distill- 开头」找产物，会扫到 gate 不管的 md（本次 26 份 vs gate 18 份）。要报可比数字，先把 `distill gate --recursive --json` 的 target 清单喂给它，diff 会很大，别混着说。
- 回归：`tests/run_gate_tests.py` 的 `hollow-probe` 断言「掏空后不许 PASS，且 conclusions/refs/links/write-integrity 不得计入格式门」。

## 已知局限（不要当成全覆盖）

- 只判结构，判不了「锚点是否指向真实存在的内容」（文件存在≠证据成立）。
- 中英文混排时按字符长度计数，阈值对极短 bullet 可能偏松。
- 不检查 PDF/图片/表格类产物；此类产物需人工核对来源。
- 对 `[I]` 的使用位置只做统计，不校验它是否出现在「必查结论」段——那一条靠 S5/S6 的人工纪律。
- `index` 的路径锚点反查会对每个锚点重读一次目标文件；产物锚点上千时耗时会线性上涨（43 处锚点实测 328ms），未做缓存。产物量级到千处时再考虑按文件缓存指纹。
