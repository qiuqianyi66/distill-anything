---
name: narr-half-report
description: 审计夹具：一条结论同时挂自述与代码两个锚点，不得算成叙述型单源
source: 自造夹具，用于 audit_evidence.py 的 narrative 表回归
---

# 夹具：两个锚点一自述一代码

裸 ref 会抛 INVALID_ARGS，与自述里「只接受完整 ref」一致，说明校验在入口 [D] E-44440001 + E-44440002
