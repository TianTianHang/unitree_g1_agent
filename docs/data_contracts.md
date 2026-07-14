# G1 Agent 数据契约

本文是当前项目内部核心控制链的契约真相。核心 topic 使用
`g1_agent_msgs` 的强类型 ROS 2 消息，不携带 JSON，也不使用
`schema_version` 字段。WebSocket、HTTP/Pi RPC、调试日志和 Unitree 官方
字符串载荷仍可在明确边界使用 JSON。

## 核心流向

```text
/audio_msg ──native JSON──> g1_interface ──VoiceEvent──┐
                                                       ├─> voice_bridge
asr_node ───────────────────────────────VoiceEvent─────┘
  └─> LocoIntent / ActionIntent
        └─> safety_control
              └─> ValidatedLocoCommand / ValidatedActionCommand
                    └─> g1_interface ──Unitree Request.parameter JSON──> Sport API
```

## Topic 类型表

| Topic | ROS 类型 | Producer | Consumer |
| --- | --- | --- | --- |
| `/g1/audio/asr` | `g1_agent_msgs/msg/VoiceEvent` | `asr_node` 或 `g1_interface` | `voice_bridge`、调试面板 |
| `/g1/audio/event` | `g1_agent_msgs/msg/VoiceEvent` | `g1_interface` | rosbag 或外部状态监听器 |
| `/voice/cmd/loco` | `g1_agent_msgs/msg/LocoIntent` | `voice_bridge` | `safety_control`、调试面板 |
| `/voice/cmd/action` | `g1_agent_msgs/msg/ActionIntent` | `voice_bridge` | `safety_control`、调试面板 |
| `/g1/state/low` | `g1_agent_msgs/msg/RobotStateSummary` | `g1_interface` | `safety_control` |
| `/g1/state/mode` | `g1_agent_msgs/msg/RobotStateSummary` | `g1_interface` | `safety_control`、`voice_bridge`、调试面板 |
| `/g1/safe_cmd/loco` | `g1_agent_msgs/msg/ValidatedLocoCommand` | `safety_control` | `g1_interface`、调试面板 |
| `/g1/safe_cmd/stop` | `g1_agent_msgs/msg/ValidatedActionCommand` | `safety_control` | `g1_interface`、调试面板 |
| `/g1/safety/decisions` | `g1_agent_msgs/msg/SafetyDecision` | `safety_control` | 调试面板、审计工具 |
| `/g1/state/safety` | `g1_agent_msgs/msg/SafetyStatus` | `safety_control` | `g1_interface`、`voice_bridge`、调试面板 |
| `/g1/state/health` | `diagnostic_msgs/msg/DiagnosticArray` | `g1_interface` | `safety_control`、`voice_bridge`、调试面板 |

所有 producer 与 consumer 必须使用同一个生成消息类；禁止在表中 topic 上
重新引入 `String` 包装层。

## 八个消息类型

### `VoiceEvent.msg`

常量：

- `EVENT_ASR="asr"`
- `EVENT_PLAYBACK="playback"`
- `PLAYBACK_STOPPED=0`
- `PLAYBACK_PLAYING=1`

字段：

| 字段 | 含义 |
| --- | --- |
| `stamp` | ROS 消息时间戳 |
| `source` | `custom_asr`、`builtin_asr`、`builtin_audio` 或调试来源 |
| `event_type` | `EVENT_ASR` 或 `EVENT_PLAYBACK` |
| `has_sequence_id`, `sequence_id` | 是否存在来源序列号及其值 |
| `text` | ASR 文本；播放事件可为空 |
| `has_confidence`, `confidence` | 是否存在置信度；存在时范围为 0.0–1.0 |
| `is_final` | ASR 是否为最终结果 |
| `language` | BCP-47 风格语言标识；未知可为空 |
| `has_playback_state`, `playback_state` | 是否存在播放状态及其枚举值 |

`has_*` 为 `false` 时，对应值字段必须被 consumer 视为未提供，而不是默认值。

### `LocoIntent.msg`

| 字段 | 含义与单位 |
| --- | --- |
| `created_at` | intent 的 ROS 创建时间戳 |
| `source` | intent producer，例如 `voice_bridge` |
| `session_id` | 会话关联标识 |
| `command_id` | 非空的关联与审计标识；可供上层实现幂等检查 |
| `text` | 触发该 intent 的原始文本 |
| `vx` | 前后线速度，m/s |
| `vy` | 横向线速度，m/s |
| `vyaw` | 偏航角速度，rad/s |
| `duration` | 运动持续时间，ROS `Duration`，单位秒/纳秒 |

### `ActionIntent.msg`

常量：`ACTION_STOP="stop"`、`ACTION_CANCEL="cancel"`、
`PRIORITY_NORMAL="normal"`、`PRIORITY_EMERGENCY="emergency"`。

字段 `created_at`、`source`、`session_id`、`command_id`、`text` 与
`LocoIntent` 同义；`action` 必须是 stop 或 cancel，`priority` 必须是
normal 或 emergency。stop/cancel 是安全动作，不是普通运动指令。

### `RobotStateSummary.msg`

模式常量：`MODE_UNKNOWN`、`MODE_SPORT_API_LOCO`、`MODE_USER_CTRL`、
`MODE_ARMED`。控制方常量：`OWNER_UNKNOWN`、`OWNER_INTERNAL`、
`OWNER_USER`。健康常量：`HEALTH_UNKNOWN`、`HEALTH_OK`、
`HEALTH_DEGRADED`、`HEALTH_UNHEALTHY`。

| 字段 | 含义与单位 |
| --- | --- |
| `stamp`, `source` | 状态时间戳与来源 topic/node |
| `mode`, `control_owner`, `mode_source` | 归一化模式、控制所有者及判断来源 |
| `has_sport_fsm_mode`, `sport_fsm_mode` | 可选的 Unitree Sport FSM mode |
| `has_sport_fsm_id`, `sport_fsm_id` | 可选的 Unitree Sport FSM id |
| `rpy` | roll/pitch/yaw，rad |
| `orientation` | ROS quaternion，x/y/z/w |
| `angular_velocity` | IMU 角速度，rad/s |
| `linear_acceleration` | IMU 线加速度，m/s² |
| `motor_count` | 当前 lowstate 中的电机数 |
| `has_max_temperature`, `max_temperature_c` | 可选最高电机温度，°C |
| `has_battery_voltage`, `battery_voltage` | 可选电池电压，V |
| `velocity`, `velocity_source` | `Twist` 速度及其来源；线速度 m/s、角速度 rad/s |
| `health_state` | 归一化健康状态 |
| `has_lowstate_age`, `lowstate_age` | 可选 lowstate 年龄，ROS `Duration` |

### `SafetyDecision.msg`

常量：`KIND_LOCO="loco"`、`KIND_ACTION="action"`、
`DECISION_ALLOW="allow"`、`DECISION_REJECT="reject"`。

字段包括 `stamp`、`command_id`、`command_kind`、`decision`、人可读的
`reason`、ROS `Duration` 类型的 `validation_latency`，以及作出决定时的
`RobotStateSummary robot_state` 快照。

### `SafetyStatus.msg`

字段包括 `stamp`、`node_name`、`enabled`、`strict_mode`、当前
`robot_state`、`allow_count`、`reject_count`、0.0–1.0 的
`rejection_rate`、`last_rejection_reason`，以及
`has_last_decision`/`last_decision`。尚无决定时 `has_last_decision=false`，
consumer 不得读取默认构造的 `last_decision` 作为真实审计记录。

### `ValidatedLocoCommand.msg`

包含完整原始 `LocoIntent intent`、校验完成时间 `validated_at` 和
`SafetyDecision validation`。`g1_interface` 必须核对 command ID、kind 和
`DECISION_ALLOW`，并再次执行有限值与范围检查。

### `ValidatedActionCommand.msg`

包含完整原始 `ActionIntent intent`、校验完成时间 `validated_at` 和
`SafetyDecision validation`。只允许已校验的 stop/cancel；二者最终都生成
零速度 Sport API 请求。

## 时间、安全与优先级语义

- ROS `Time`/`Duration` 用于消息传输、rosbag 和审计。
- deadline、watchdog、freshness 和 API timeout 的本地判断必须使用单调
  时钟；不得用可能跳变的 wall clock 或 ROS stamp 推导本地 deadline。
- 正常 loco 需要 fresh lowstate、fresh safety heartbeat、fresh mode 查询、
  internal `sport_api_loco` ownership，且不能有未确认的 velocity 请求。
- stop/cancel、watchdog stop 和 shutdown stop 不得被 stale lowstate、模式
  状态或 safety heartbeat 阻止。
- 同一处理窗口内同时出现 stop 和 loco 时，stop 必须优先。

## ASR 来源模式

`g1_interface` 的 `asr.source_mode` 定义原生 ASR 与自定义 ASR 的关系：

- `builtin`：转发 native `/audio_msg` 中的 ASR 事件；
- `custom`：不转发 native ASR，由 `asr_node` 发布；
- `both`：两种来源都可发布到 `/g1/audio/asr`；producer 必须正确标记
  `source` 和可用的 `sequence_id`，便于观测与上层去重。

播放状态仍由 `/audio_msg` 转换为 `/g1/audio/event` 的 `VoiceEvent`。

## 允许保留 JSON/String 的边界

- Unitree 原生 `/audio_msg` 使用官方 `std_msgs/msg/String` 载荷；
  `g1_interface` 在此边界解析 ASR/播放 JSON 并转为 `VoiceEvent`。
- Unitree `unitree_api/msg/Request.parameter` 以及 response 的字符串载荷按
  官方 Sport/Voice API 继续使用 JSON。
- Pi Agent JSONL RPC、外部 HTTP、WebSocket 和调试日志继续使用 JSON。
- `/g1/state/motors` 是本阶段未迁移的非核心监控 topic，可暂时保留
  `std_msgs/msg/String`。
- `/voice/state`、`/voice/debug/events`、TTS 与 LED 是状态、调试或外部设备
  边界，不属于上表的强类型运动控制链。
