---
name: sample-missing-ref
description: 测试样例（必须被判 FAIL），模拟引用不存在的参考文件
---

# sample 机制

## 结构地图
- 入口注册在 `src/core.ts:42`，向三条下游分发 [O] src/core.ts:42-58
- 限流放在中间件层而非路由层 [D] src/app.ts:31 + src/mw/ratelimit.ts:12
- 配置默认值以代码为准，README 的示例落后一个版本 [O] src/config.ts:88

## 细节表
见 `references/not-exists.md`，那里有完整探针清单。

## 可搬机制
- 用中间件统一限流：改动面小且可测 [D] src/mw/ratelimit.ts:12 + src/app.ts:31
- 配置默认值集中一处，避免文档与代码漂移 [O] src/config.ts:88
- 日志结构化，便于机器聚合 [O] src/log.ts:15

## 证据台账
| 结论 | 层级 | 锚点 |
|---|---|---|
| 限流在中间件层 | D | src/app.ts:31 |

## 诚实边界
- 只覆盖 src/ 目录
- 静态差异不是因果 [I]

## 未知台账
| 未知 | 为什么解不了 | 需要什么才能解 |
|---|---|---|
| 集群模式行为 | 无多实例日志 | 集群部署日志 |
| 阈值标定 | 无压测 | 压测数据 |
| 启动幂等性 | 未重复启动 | 可重复启动沙箱 |
