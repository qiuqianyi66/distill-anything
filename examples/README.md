# 示例作品

这里是两份真实蒸馏成品，已脱敏：不含本地绝对路径、个人信息、主机名或凭据，只保留可公开的判据与证据结构。

每份都是自包含的：`report.md` 是产物正文，`evidence.jsonl` 是它引用的证据库，正文里的 `E-xxxxxxxx` 都能在证据库里查到对应条目和原文指纹。

| 示例 | 类型 | 对象 | 看点 |
|---|---|---|---|
| [`auto-ontology/`](auto-ontology/report.md) | rules | NVIDIA Auto-Ontology 的技能层治理规则 | 判据表、假阳性排除、根因层、降级路径、运行安全 |
| [`scrapling/`](scrapling/report.md) | mechanism | Scrapling 抓取框架 | 分层机制、关键契约、失效降级、外部审视、运行安全 |

## 怎么读

1. 先看 `report.md`：每条结论后面都挂着 `[O]/[D]/[I]` 标记和一个 `E-` 锚点，而不是裸观点。
2. 再对照 `evidence.jsonl`：用 `E-` id 找到证据条目，里面有相对路径、行段、原文指纹 `quote_sha1` 和公开来源 `source_ref`。
3. 原文一旦改动，`quote_sha1` 就对不上，门禁会把该证据标记为已变，要求重读——这就是「文件一改门禁就知道」。

这些示例展示的是方法产物的形态，不是目标对象的完整复刻；原始 `raw/` 现场未随示例上传。
