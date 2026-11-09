---
name: sample-lib-mechanism
description: 测试样例（非真实结论），用于验证门禁的 PASS 路径
source: out/distill-sample/fixtures/good.md
---

# sample-lib 机制

## 结构地图
- 入口注册在 `src/core.ts:3`，向三条下游分发 [O] src/core.ts:3-7
- 限流放在中间件层而非路由层 [D] src/app.ts:4 + src/mw/ratelimit.ts:4
- 配置默认值以代码为准，README 的示例落后一个版本 [O] src/config.ts:5

## 关键决策与代价
- 选择内存队列换取零外部依赖，代价是重启丢任务 [D] src/queue/mem.ts:3 + src/queue/mem.ts:9
- 日志统一走结构化输出，代价是可读性下降 [O] src/log.ts:5 https://example.com/docs/logging

| 决策 | 换取 | 代价 | 证据 |
|---|---|---|---|
| 内存队列 | 零依赖 | 重启丢任务 | src/queue/mem.ts:3 |

## 可搬机制
- 用中间件统一限流：改动面小且可测，前置条件是所有路由走同一条链 [D] src/mw/ratelimit.ts:4 + src/app.ts:4
- 配置默认值集中一处，避免文档与代码漂移 [O] src/config.ts:5

## 明确不搬
- 自研序列化协议不搬：本项目无跨语言需求，迁移成本高于收益 [I] 未验证，仅按项目边界判断
- 手工编排的启动顺序不搬：缺少幂等保证，搬来会放大故障面 [D] src/boot/order.ts:4 + src/boot/order.ts:9

## 证据台账
| 结论 | 层级 | 锚点 |
|---|---|---|
| 限流在中间件层 | D | src/app.ts:4, src/mw/ratelimit.ts:4 |
| README 示例落后一版 | O | src/config.ts:5 |

## 诚实边界
- 本次只覆盖 src/ 目录，未覆盖 native/ 与 tests/
- 静态差异是候选不是因果 [I]
- 版本固定在样例 commit，之后可能已变

## 未知台账
| 未知 | 为什么解不了 | 需要什么才能解 |
|---|---|---|
| 队列在集群模式下的行为 | 无多实例测试 | 需要集群部署日志 |
| 限流阈值如何标定 | 无压测记录 | 需要压测数据 |
| 启动顺序是否幂等 | 未跑重复启动 | 需要可重复启动的沙箱 |
