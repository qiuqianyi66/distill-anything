---
name: narr-docs-report
description: 审计夹具：raw 只有自述文档，结论全挂自述属结构性 100%，不应告警
source: 自造夹具，用于 audit_evidence.py 的 narrative 表回归
---

# 夹具：只有文档的对象

它要求安装路径最后一段必须是自己的名字，否则拒绝安装 [O] E-22220001

它把配置写在仓库根的 hosts.json，而不是环境变量 [O] E-22220002
