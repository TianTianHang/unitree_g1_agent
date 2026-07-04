# Voice Bridge Node P0 Design

**目标:** 设计 `src/voice_bridge` ROS2 Python 节点，恢复语音控制主链路：接收 `/g1/audio/asr` 文本，调用或模拟 Pi Agent，输出运动意图到 `/voice/cmd/*`，输出 TTS/LED 反馈到 `/g1/cmd/audio/*`。P0 不直接控制机器人，不发布 `/api/*`、`/lowcmd`、`/arm_sdk`、`/dex3/*/cmd` 或 `/g1/safe_cmd/*`。

**当前约束:** 仓库里已有 `src/g1_interface` P0，内部接口大量使用 `std_msgs/String` 承载 JSON。`safety_controller` 尚未实现，因此语音节点 P0 的真机运动闭环依赖后续安全节点；在安全节点完成前，只做单元测试、topic wiring 和 mock subscriber 验证。

## 1. 边界和职责

### 1.1 语音节点负责

- 订阅 ASR 文本事件 `/g1/audio/asr`。
- 维护会话状态：未唤醒、已唤醒、处理中、等待确认、超时。
- 识别停止/取消类高优先级指令，并立即发布 `/voice/cmd/action`。
- 将普通 ASR 文本、机器人状态和可选视觉上下文传给 Pi Agent 适配层。
- 将 Pi Agent 返回的结构化结果转成 ROS2 内部 topic：
  - `/voice/cmd/loco`
  - `/voice/cmd/action`
  - `/g1/cmd/audio/tts`
  - `/g1/cmd/audio/led`
- 发布 `/voice/state`，便于调试会话、最近 ASR、最近动作和 agent 错误。

### 1.2 语音节点不负责

- 不做最终安全限幅和模式门控；这些属于 `safety_controller`。
- 不直接下发 `/g1/safe_cmd/loco` 或 `/g1/safe_cmd/stop`。
- 不访问 Unitree 原生 `/api/voice/*`；TTS/音量/LED 仍通过 G1 接口节点适配到底层。
- 不把低层控制、模式切换、手臂 SDK 或 Dex3 命令暴露给语音。
- 不在 Pi Agent 超时后重放运动命令。

## 2. ROS2 接口

P0 沿用 `std_msgs/msg/String` + JSON，保持和现有 `g1_interface` 风格一致。后续接口稳定后再抽自定义 msg。

### 2.1 订阅

| Topic | Type | 用途 |
| --- | --- | --- |
| `/g1/audio/asr` | `std_msgs/msg/String` | ASR 文本事件。支持 JSON 或纯文本。 |
| `/g1/state/mode` | `std_msgs/msg/String` | 当前机器人模式摘要，可传给 agent。 |
| `/g1/state/safety` | `std_msgs/msg/String` | 安全状态，可传给 agent 并影响反馈。 |
| `/g1/state/health` | `diagnostic_msgs/msg/DiagnosticArray` | 底层健康状态，用于状态提示和 agent context。 |
| `/camera/rgb/image_raw` | `sensor_msgs/msg/Image` | P1 可选；P0 默认不启用。 |

### 2.2 发布

| Topic | Type | 用途 |
| --- | --- | --- |
| `/voice/cmd/loco` | `std_msgs/msg/String` | 高层移动意图，给安全节点消费。 |
| `/voice/cmd/action` | `std_msgs/msg/String` | 停止、取消、站立、恢复等离散意图。 |
| `/g1/cmd/audio/tts` | `std_msgs/msg/String` | TTS 文本请求，给 G1 接口节点消费。 |
| `/g1/cmd/audio/led` | `std_msgs/msg/String` | LED 反馈请求，给 G1 接口节点消费。 |
| `/voice/state` | `std_msgs/msg/String` | 语音节点状态和调试摘要。 |

## 3. JSON 数据格式

### 3.1 ASR 输入

`/g1/audio/asr` 首选 JSON：

```json
{
  "text": "宇树，向前走一秒",
  "confidence": 0.92,
  "is_final": true,
  "source": "g1_asr",
  "stamp": "2026-07-04T10:00:00Z"
}
```

兼容纯文本输入，例如 `宇树，向前走一秒`。纯文本按 `is_final=true`、`confidence=null` 处理。

低置信度和非 final 结果默认不触发运动：

- `min_confidence`: 默认 `0.5`；`confidence=null` 视为可用。
- `process_partial`: 默认 `false`。

### 3.2 `/voice/cmd/loco`

```json
{
  "source": "voice_bridge",
  "session_id": "20260704T100000.123Z",
  "command_id": "20260704T100002.010Z-1",
  "text": "向前走一秒",
  "vx": 0.25,
  "vy": 0.0,
  "vyaw": 0.0,
  "duration_sec": 1.0
}
```

约束：

- 语音节点必须填 `duration_sec`；如果 agent 未给出，使用 `default_motion_duration_sec`。
- P0 默认只允许短动作，`duration_sec <= 2.0`；更长动作由安全节点最终拒绝或截断。
- 语音节点可以做基本格式校验，但不能把自己的校验当作安全保证。

### 3.3 `/voice/cmd/action`

```json
{
  "source": "voice_bridge",
  "session_id": "20260704T100000.123Z",
  "command_id": "20260704T100001.001Z-stop",
  "action": "stop",
  "priority": "emergency",
  "text": "停止"
}
```

P0 动作集合：

- `stop`: 停止/别动/取消。无需唤醒，最高优先级。
- `cancel`: 取消当前会话或等待中的 agent 请求。
- `stand`: 站立意图，需安全节点和底层支持后再启用。
- `resume`: 恢复普通会话，不直接恢复运动。

### 3.4 `/g1/cmd/audio/tts`

```json
{
  "source": "voice_bridge",
  "session_id": "20260704T100000.123Z",
  "text": "收到",
  "speaker_id": 0,
  "interrupt": true
}
```

### 3.5 `/g1/cmd/audio/led`

```json
{
  "source": "voice_bridge",
  "r": 0,
  "g": 120,
  "b": 255,
  "ttl_sec": 1.0
}
```

## 4. 会话状态机

```text
IDLE
  ├─ wake word / direct command → ACTIVE
  ├─ stop word                  → publish stop action, stay IDLE
  └─ other text                 → ignore

ACTIVE
  ├─ final ASR                  → AGENT_PENDING
  ├─ stop word                  → publish stop action, cancel agent, IDLE
  └─ idle timeout               → IDLE

AGENT_PENDING
  ├─ agent result: loco/action  → publish intent, ACTIVE
  ├─ agent result: speak/led    → publish feedback, ACTIVE
  ├─ agent timeout/error        → publish TTS error only, ACTIVE
  └─ stop word                  → publish stop action, cancel agent, IDLE
```

规则：

- 未唤醒时只处理唤醒词和停止词。
- 如果文本同时包含唤醒词和命令，例如 `宇树，向前走一秒`，语音节点进入 `ACTIVE` 后立即处理剩余命令。
- 停止词不等待 Pi Agent，直接发布 `/voice/cmd/action`。
- Agent 失败时只允许发布 TTS/LED 反馈，不允许重放上一条运动。
- 会话超时后清空最近 agent 结果和待确认动作。

## 5. Pi Agent 适配层

定义一个纯 Python 协议，节点只依赖协议，不依赖具体 agent 运行时：

```python
class AgentClient(Protocol):
    def decide(self, request: AgentRequest) -> AgentResult:
        ...
```

### 5.1 AgentRequest

字段：

- `session_id`
- `text`
- `asr_confidence`
- `robot_mode`
- `safety_state`
- `health_state`
- `image_ref`，P1 可选

### 5.2 AgentResult

字段：

- `commands`: list of structured commands
- `reply_text`: optional TTS
- `led`: optional RGB
- `requires_confirmation`: bool，P0 对运动默认不使用确认；P1 可用于手臂/模式类动作

命令类型：

- `loco`: `vx`, `vy`, `vyaw`, `duration_sec`
- `action`: `stop`, `cancel`, `stand`, `resume`
- `say`: `text`
- `led`: `r`, `g`, `b`, `ttl_sec`
- `none`: 只更新会话，不发布动作

### 5.3 P0 适配器

- `rule_based`: 默认本地适配器，用于开发和测试。识别中文关键词：
  - `向前/前进`: `vx=+default_vx`
  - `后退`: `vx=-default_vx`
  - `左移`: `vy=+default_vy`
  - `右移`: `vy=-default_vy`
  - `左转`: `vyaw=+default_vyaw`
  - `右转`: `vyaw=-default_vyaw`
  - `停止/别动/取消`: action `stop`
- `http_json`: 可选适配器，向 Pi Agent HTTP endpoint 发送 JSON，超时默认 `2.0s`。
- `disabled`: 只处理停止词和 TTS，不产生运动。

P0 实现优先用 `rule_based` 跑通 ROS2 topic 和测试；接入真实 Pi Agent 时只替换 `AgentClient`。

## 6. 配置

默认配置文件：`src/voice_bridge/config/voice_bridge.yaml`

```yaml
voice:
  wake_words: ["宇树", "小宇"]
  stop_words: ["停止", "停下", "别动", "取消", "stop"]
  idle_timeout_sec: 20.0
  max_session_sec: 300.0
  min_confidence: 0.5
  process_partial: false

motion_defaults:
  default_vx: 0.25
  default_vy: 0.15
  default_vyaw: 0.5
  default_motion_duration_sec: 1.0
  max_motion_duration_sec: 2.0

agent:
  backend: rule_based
  http_endpoint: ""
  timeout_sec: 2.0

topics:
  asr: /g1/audio/asr
  voice_loco: /voice/cmd/loco
  voice_action: /voice/cmd/action
  tts: /g1/cmd/audio/tts
  led: /g1/cmd/audio/led
  voice_state: /voice/state
  robot_mode: /g1/state/mode
  safety_state: /g1/state/safety
  health: /g1/state/health
```

## 7. 实现结构

```text
src/voice_bridge/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/voice_bridge
├── config/voice_bridge.yaml
├── launch/voice_bridge.launch.py
├── voice_bridge/
│   ├── __init__.py
│   ├── agent.py          # AgentClient, rule_based/http_json adapters
│   ├── config.py         # YAML config and validation
│   ├── internal_types.py # ASR event, agent request/result, session state
│   ├── intent.py         # ASR parsing, wake/stop detection, command building
│   └── node.py           # rclpy wiring
└── tests/
    ├── test_config.py
    ├── test_intent.py
    ├── test_agent_rule_based.py
    └── test_node_helpers.py
```

## 8. 测试设计

### 8.1 单元测试

- `config.py`
  - 默认 topic 名称正确。
  - YAML override 正常合并。
  - 非法 agent backend、负超时、空 topic 被拒绝。
- `intent.py`
  - JSON ASR 和纯文本 ASR 都能解析。
  - 非 final ASR 默认不触发。
  - 低置信度 ASR 不触发运动。
  - 未唤醒时普通文本被忽略。
  - 未唤醒时停止词仍发布 stop action。
  - 唤醒词和命令同句时能处理剩余命令。
- `agent.py`
  - rule_based 能生成前进/后退/左右转/停止结果。
  - 未识别文本只返回 TTS，不产生运动。
  - agent timeout 模拟不产生运动重发。
- `node.py`
  - ASR stop 输入发布 `/voice/cmd/action`。
  - ASR movement 输入发布 `/voice/cmd/loco`。
  - agent error 只发布 `/g1/cmd/audio/tts`。

### 8.2 回环验证

安全节点完成前，只做 topic 验证：

```bash
ros2 launch voice_bridge voice_bridge.launch.py \
  config_path:=src/voice_bridge/config/voice_bridge.yaml

ros2 topic echo /voice/cmd/loco
ros2 topic echo /voice/cmd/action
ros2 topic echo /g1/cmd/audio/tts

ros2 topic pub /g1/audio/asr std_msgs/msg/String \
  '{data: "{\"text\":\"宇树，向前走一秒\",\"confidence\":0.9,\"is_final\":true}"}' --once

ros2 topic pub /g1/audio/asr std_msgs/msg/String \
  '{data: "停止"}' --once
```

真机运动验证必须等 `safety_controller` P0 完成后执行。

## 9. 分阶段交付

### Task 1: Scaffold And Config

- [x] 创建 `src/voice_bridge` ROS2 Python package。
- [x] 实现 `VoiceBridgeConfig.default()` 和 `from_yaml()`。
- [x] 添加默认 `voice_bridge.yaml` 和 launch 文件。
- [x] 用 pytest 覆盖默认值、override 和非法配置。

### Task 2: Intent And Session Logic

- [x] 实现 ASR 解析，兼容 JSON 和纯文本。
- [x] 实现 wake word、stop word、低置信度、非 final 过滤。
- [x] 实现会话状态和超时逻辑。
- [x] 添加 focused unit tests。

### Task 3: Agent Adapter

- [x] 定义 `AgentClient`、`AgentRequest`、`AgentResult`。
- [x] 实现 `rule_based` backend。
- [x] 预留 `http_json` backend，至少完成请求/响应 schema 和超时处理。
- [x] 添加 rule_based 和 payload 单元测试。

### Task 4: ROS2 Node Wiring

- [x] 订阅 `/g1/audio/asr`、`/g1/state/mode`、`/g1/state/safety`、`/g1/state/health`。
- [x] 发布 `/voice/cmd/loco`、`/voice/cmd/action`、`/g1/cmd/audio/tts`、`/g1/cmd/audio/led`、`/voice/state`。
- [x] 停止词绕过 agent，直接发布 action。
- [x] Agent error 只发布反馈，不发布运动。
- [x] 添加 node helper 单元测试。

### Task 5: Documentation And Verification

- [x] 新增 `src/voice_bridge/README.md`。
- [x] 跑 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/voice_bridge .venv/bin/python -m pytest src/voice_bridge/tests -q`。
- [x] 在 ROS2 环境下跑回环 topic 验证。
- [x] 在 `docs/设计文档.md` 记录实现状态。

## 10. 验收标准

- ASR 文本可以进入语音节点并更新 `/voice/state`。
- `停止`、`别动`、`取消` 不需要唤醒即可发布 `/voice/cmd/action`。
- `宇树，向前走一秒` 在 `rule_based` backend 下发布 `/voice/cmd/loco`。
- 运动意图只发到 `/voice/cmd/*`，不会绕过安全节点。
- Agent 超时或异常不会产生运动命令。
- 单元测试覆盖配置、意图解析、rule_based agent 和 node helper。
