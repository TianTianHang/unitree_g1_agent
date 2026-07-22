# G1 Low-Level Guard

`low_level_guard` 是项目内唯一允许发布真实 `/lowcmd` 的节点。模型后端输出 29 路关节
阻抗候选命令，guard 在 lease、机器人状态和候选时效均有效时，将其映射为 Unitree
35 槽 `LowCmd`。

## 控制链

```text
motion manager ──LowLevelControlLease──────────────┐
                                                   ├─> low_level_guard ─> /lowcmd
motion backend ──LowLevelCommandCandidate (29)────┤
                                                   │
/lowstate ─────────────────────────────────────────┘
```

每路候选包含：

```text
q, dq, tau, kp, kd
```

guard 负责：

- 校验 lease、request、robot profile 和 control profile；
- 拒绝重复或倒退的 sequence ID；
- 拒绝 NaN/Inf、越界增益、力矩、速度和过大位置跳变；
- 使用单调时钟判断 lease、candidate 和 lowstate 新鲜度；
- 从 fresh lowstate 复制 `mode_machine`；
- 将前 29 个 motor slot 设为 enabled，将 29～34 设为 disabled；
- 清零 reserve 并计算 Unitree CRC；
- 以配置的高频率重复发布最近一帧合法候选。

## 启动

```bash
source /opt/ros/foxy/setup.bash
source .unitree/unitree_ros2/cyclonedds_ws/install-foxy/setup.bash
source install-foxy/setup.bash
ros2 launch low_level_guard low_level_guard.launch.py
```

默认 topic：

| Topic | 类型 |
|---|---|
| `/g1/low_level/lease` | `g1_agent_msgs/msg/LowLevelControlLease` |
| `/g1/low_level/candidate` | `g1_agent_msgs/msg/LowLevelCommandCandidate` |
| `/lowstate` | `unitree_hg/msg/LowState` |
| `/lowcmd` | `unitree_hg/msg/LowCmd` |
| `/g1/low_level_guard/diagnostics` | `diagnostic_msgs/msg/DiagnosticArray` |

## 当前故障行为

当 lease、candidate 或 lowstate 失效时，guard 立即停止发布新的 LowCmd，并通过 diagnostics
报告原因。仓库当前没有假设“停止发布”等同于机器人安全停止；目标固件的 hold、damping、
zero-torque 和物理急停行为必须在真机验证后，作为明确的退出 profile 加入 guard。

在该退出策略完成前，不应把 guard 的 timeout 描述为完整的真机急停保证。
