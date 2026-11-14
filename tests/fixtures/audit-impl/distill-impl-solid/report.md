# x 机制

## 结构地图
入口一个 [O] E-aaaa1111

## 3.5 实现层事实（计划）
- 状态机五值：`needs_configuration` 与 `missing` 按注册状态自上而下判定 [O] E-bbbb2222
- 计划前置：`planSetupActions` 在 client 未注册时直接返回空计划 [O] E-cccc3333
- 例外：装引擎时回写 `HOPPER_LAUNCHER_PATH`，原本正确也要再写一次 [O] E-dddd4444
