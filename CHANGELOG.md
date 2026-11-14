# Changelog

版本以 `SKILL.md` 的 `version:` 字段为准；判据口径与每次偏差的完整留痕在 `references/quality-gate.md`，不在此重复。

## [1.1.38] - 2026-11-14

> 1.1.32–1.1.38 为本地合并批次，随本次一起发布（git 上对应合并提交 `5ae7176`）。

### Added
- `scripts/material_audit.py`：只读材料体检，识别空文件 / 非 UTF-8 / 需转换二进制 / 可疑未知 / 超大文本（>8MB），每类给一行处理路线；自测 7/7。
- `references/material-intake.md`：准入四问、18 类材料分型、五个出口（拒收 / 降级 / 换源 / 抽样 / 挂起）、12 个行业场景矩阵、转换件四行写法、8 条反模式、3 条验收。

## [1.1.37] - 2026-11-14

### Fixed
- `score_product.py` D3 补「表格兜底列」形态：rules 型判据表的「仍失败兜底」列计入 D3，修复 9 份 D3=0 中 7 份误判；`--selftest` 16→17。

## [1.1.36] - 2026-11-14

### Fixed
- `MATERIAL` 白名单补 `CODE_SUFFIX`（js/mjs/go/rs/…），修「只有 .mjs 的仓库实现层读数假 0%」。
- `distill-distilly-repo`、`distill-nuwa-method` 补齐实现层事实节（各 3 行，全实心）。

### Changed
- `tests/run_audit_tests.py` 36→39 项，夹具 5 个。

## [1.1.35] - 2026-11-14

### Changed
- `score_product.py` 总分口径改为 D1–D5 之和（上限 50）；D6 派生、D7 人工均不并入。JSON 新增 `total_max` / `composed` / `derived_not_in_total`；`--selftest` 8→16。

## [1.1.34] - 2026-11-11

### Added
- `audit_evidence.py` 第五张表「实现层事实实心率」（机制型 + raw 含代码对象才出数）。

### Changed
- `tests/run_audit_tests.py` 18→36 项，夹具 4 个。

## [1.1.33] - 2026-11-11

### Added
- `references/templates/mechanism.md` 增条件节「实现层事实」（对象含代码材料时必写）：状态机 / 阻断条件 / 阈值与例外，三行各带 `[O] <路径:行>`。

## [1.1.32] - 2026-11-11

### Added
- `audit_evidence.py` 第四张表「叙述型单源率」+ `--json`。
- `tests/run_audit_tests.py` 18/18、夹具 4 个。

## [1.1.31] - 2026-11-11

### Added
- `scripts/audit_evidence.py`：一次出三张观察表——具体性密度 / raw 材料进证据率 / 上游漂移（`--remote` 走 `gh api`）。只报观察、不下判定。
- `SKILL.md` S8.5 交付前体检。

### Changed
- `tests/run_gate_tests.py` 回归 44/44。

## [1.1.30] - 2026-11-11

### Added
- 先验快照（S2.5）与增量判据（S4 增量四分类 + 增量测试），治「蒸馏不完整」。

## docs - 2026-11-14（提交 `c0593cd`）

### Changed
- README 重写：中英双段、效果示例、安装矩阵、五张观察表、FAQ、来源致敬。
- 新增 `llms.txt`、`assets/banner.svg`、MIT `LICENSE`。
- `SKILL.md` description 补英文检索词。
