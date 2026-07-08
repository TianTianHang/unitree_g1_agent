# G1 Agent 数据契约

本文固定当前三个 P0 节点之间的 JSON 数据结构。开发阶段不保留旧结构兼容性；代码和测试以本文为准。

## 总体流向

```text
g1_interface
  subscribes /audio_msg
  publishes /g1/audio/asr, /g1/audio/event, /g1/state/low, /g1/state/mode, /g1/state/health

voice_bridge
  subscribes /g1/state/mode, /g1/state/safety, /g1/state/health
  publishes /voice/cmd/loco, /voice/cmd/action

safety_control
  subscribes /voice/cmd/loco, /voice/cmd/action, /g1/state/low, /g1/state/mode, /g1/state/health
  publishes /g1/safe_cmd/loco, /g1/safe_cmd/stop, /g1/safety/decisions, /g1/state/safety

g1_interface
  subscribes /g1/safe_cmd/loco, /g1/safe_cmd/stop
  publishes /api/sport/request
```

## g1_interface 发布结构

### `/g1/state/low`

`std_msgs/msg/String`，JSON：

```json
{
  "schema_version": "g1_state.v1",
  "source": "lowstate",
  "stamp_sec": 10.0,
  "mode": "sport_api_loco",
  "control_owner": "internal",
  "mode_source": "sport_api.get_fsm_mode",
  "sport_fsm_mode": 2,
  "sport_fsm_id": 0,
  "rpy": [0.0, 0.0, 0.0],
  "quaternion": [1.0, 0.0, 0.0, 0.0],
  "gyroscope": [0.0, 0.0, 0.0],
  "accelerometer": [0.0, 0.0, 9.8],
  "motor_count": 35,
  "max_temperature_c": 42.0,
  "battery_voltage": null,
  "velocity": {"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
  "velocity_source": "last_sport_command"
}
```

### `/g1/state/mode`

`std_msgs/msg/String`，JSON：

```json
{
  "schema_version": "g1_state.v1",
  "source": "lf/lowstate",
  "stamp_sec": 10.0,
  "mode": "sport_api_loco",
  "control_owner": "internal",
  "mode_source": "sport_api.get_fsm_mode",
  "sport_fsm_mode": 2,
  "sport_fsm_id": 0,
  "motor_count": 35
}
```

### `/g1/state/health`

`diagnostic_msgs/msg/DiagnosticArray`。`g1_interface` 必须在 diagnostic key/value 中发布：

- `state`: `"ok" | "degraded" | "unhealthy"`
- `lowstate_age_ms`: `int | null`
- `pending_api_count`: `int`
- `last_api_result`: `object | null`

### `/g1/audio/asr`

`std_msgs/msg/String`。`g1_interface` 从 native `/audio_msg` 转发 ASR 文本事件到该项目内部 topic。

允许两种输入形态：

- plain text，例如 `停止`
- JSON object，且 `text` 字段非空，例如：

```json
{
  "index": 1,
  "timestamp": 1000000000,
  "text": "宇树，向前走一秒",
  "confidence": 0.95,
  "is_final": true,
  "language": "zh-CN"
}
```

### `/g1/audio/event`

`std_msgs/msg/String`。`g1_interface` 从 native `/audio_msg` 转发非 ASR 音频事件到该项目内部 topic。

用于桥接非 ASR 的 `/audio_msg` 消息（如播放状态 `{"play_state": 1}`），供 debug panel、音频状态监控等下游节点消费。消息原样转发，不做 schema 解析。

## voice_bridge 发布结构

### `/voice/cmd/loco`

`std_msgs/msg/String`，JSON：

```json
{
  "schema_version": "voice_command.v1",
  "source": "voice_bridge",
  "session_id": "s1",
  "command_id": "c1",
  "created_at": 10.0,
  "text": "向前",
  "vx": 0.2,
  "vy": 0.0,
  "vyaw": 0.0,
  "duration_sec": 1.0
}
```

### `/voice/cmd/action`

`std_msgs/msg/String`，JSON：

```json
{
  "schema_version": "voice_command.v1",
  "source": "voice_bridge",
  "session_id": "s1",
  "command_id": "c2",
  "created_at": 10.0,
  "action": "stop",
  "priority": "emergency",
  "text": "停止"
}
```

## safety_control 发布结构

### `/g1/safe_cmd/loco`

`std_msgs/msg/String`，JSON。保留原始命令字段，并添加验证结果。`g1_interface` 订阅此主题时必须要求 `validation_result.allowed == true`：

```json
{
  "schema_version": "voice_command.v1",
  "source": "voice_bridge",
  "session_id": "s1",
  "command_id": "c1",
  "created_at": 10.0,
  "text": "向前",
  "vx": 0.2,
  "vy": 0.0,
  "vyaw": 0.0,
  "duration_sec": 1.0,
  "validated_at": 10.02,
  "validation_result": {
    "allowed": true,
    "reason": null,
    "check_details": {}
  },
  "robot_state_snapshot": {}
}
```

### `/g1/safe_cmd/stop`

`std_msgs/msg/String`，JSON。保留 action 命令并添加验证结果。`g1_interface` 订阅此主题时必须要求 `validation_result.allowed == true` 且 `action` 为 `"stop"` 或 `"cancel"`。`stop` 和 `cancel` 是紧急通道，允许绕过普通状态检查。

### `/g1/safety/decisions`

`std_msgs/msg/String`，JSON：

```json
{
  "timestamp": 10.02,
  "command_id": "c1",
  "command_kind": "loco",
  "decision": "allow",
  "reason": null,
  "validation_time_ms": 1.2,
  "robot_state": {},
  "check_details": {}
}
```

## strict mode 策略

当前默认：

```yaml
strict_mode: true
require_command_timestamp: true
```

因此 loco 命令必须满足：

- `/g1/state/low` 或 `/g1/state/health` 提供 fresh lowstate。
- `/g1/state/mode` 或 `/g1/state/low` 提供明确 `mode`，且该 mode 来自 Sport API 查询状态。
- `/voice/cmd/loco` 提供 `created_at`，且命令未超过 `command_timeout_ms`。
- `vx/vy/vyaw/duration_sec` 在运动限制内。
- 速度变化不超过连续性限制。

Non-motion health parameters such as motor temperature and battery voltage are not part of the P0 strict requirement. They remain in `g1_state.v1` for monitoring and future policy use, and enforcement can be enabled later with `require_motor_temperature: true` or `require_battery_voltage: true`.

停止命令仍然无条件允许通过安全节点并发往 `/g1/safe_cmd/stop`。
