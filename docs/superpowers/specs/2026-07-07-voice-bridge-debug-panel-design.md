# Voice Bridge Debug Panel — 设计文档

日期：2026-07-07
状态：Draft

## 1. 目标

为 G1 机器人的 voice_bridge 提供一个 Web 调试面板，支持：

1. **ASR 输入区**：手动输入文字并配置参数（confidence、is_final 等），发布到 `/g1/audio/asr` 话题，模拟语音识别事件。
2. **Agent 输出面板**：通过 voice_bridge 专用 debug 事件实时展示 agent 的决策结果——commands 列表、reply_text、LED 指令等。
3. **决策时间线**：以时间线形式展示完整的决策链路——ASR 事件到达 → intent 解析（wake word / stop word / agent 路由）→ session 状态转换 → agent 工具调用 → 最终命令发布。voice_bridge 内部决策链路由 `/voice/debug/events` 提供，安全控制链路继续使用 `/g1/safety/decisions`。
4. **机器人状态面板**：实时显示 robot_mode、safety_state、health、voice_bridge session 状态。

## 2. 技术选型

| 层 | 技术 | 理由 |
|---|------|------|
| 后端 | Python FastAPI + rclpy | 与现有 voice_bridge 代码栈一致；FastAPI 原生支持 WebSocket 和静态文件服务 |
| 前端 | React 18 + Vite + TypeScript | 用户选择 |
| UI | TailwindCSS | 用户选择，灵活轻量 |
| 实时通信 | WebSocket（FastAPI 内置） | 服务端向客户端推送 ROS2 话题更新 |
| REST API | FastAPI HTTP 路由 | 客户端向服务端发送 ASR 发布请求等 |

## 3. 架构

```text
浏览器 (React SPA)
  ├── WebSocket ──→ FastAPI Server (Python)
  │                    ├── rclpy ROS2 Node
  │                    │   ├── subscribe /g1/audio/asr      (监听 ASR 事件)
  │                    │   ├── subscribe /voice/state         (voice_bridge 状态)
  │                    │   ├── subscribe /voice/debug/events  (voice_bridge 调试事件)
  │                    │   ├── subscribe /g1/state/mode       (机器人模式)
  │                    │   ├── subscribe /g1/state/safety    (安全状态)
  │                    │   ├── subscribe /g1/state/health     (健康状态)
  │                    │   ├── subscribe /voice/cmd/loco      (运动命令输出)
  │                    │   ├── subscribe /voice/cmd/action     (动作命令输出)
  │                    │   ├── subscribe /g1/cmd/audio/tts    (TTS 输出)
  │                    │   ├── subscribe /g1/cmd/audio/led    (LED 输出)
  │                    │   ├── subscribe /g1/safe_cmd/loco    (安全验证后运动命令)
  │                    │   ├── subscribe /g1/safe_cmd/stop    (安全验证后停止命令)
  │                    │   └── subscribe /g1/safety/decisions  (安全决策日志)
  │                    │
  │                    ├── REST POST /api/asr/publish         (发布 ASR 事件)
  │                    ├── REST POST /api/asr/quick          (快捷 ASR 发布)
  │                    ├── REST GET  /api/history              (获取历史记录)
  │                    ├── REST GET  /api/config               (获取当前配置)
  │                    └── REST GET  /api/state                (获取完整状态快照)
  │
  └── HTTP ──────────→ (同上 REST 端点)
```

### 数据流

```text
[用户输入文字] → REST POST /api/asr/publish → ASR publish queue → ROS timer drain → publish /g1/audio/asr
                                                                         ↓
                                                              voice_bridge node 处理
                                                                         ↓
                                                              发布 /voice/debug/events, /voice/cmd/loco, /voice/state 等
                                                                         ↓
                                                              DebugBridgeNode 订阅回调
                                                                         ↓
                                                              asyncio broadcast queue → WebSocket 推送给前端
                                                                         ↓
                                                              React 组件更新
```

## 4. 后端设计

### 4.1 文件结构

```
src/voice_bridge_debug/
├── setup.py
├── package.xml
├── launch/
│   └── debug_panel.launch.py
├── voice_bridge_debug/
│   ├── __init__.py
│   ├── server.py        # FastAPI app 入口，管理 ROS2 节点生命周期
│   ├── ros_node.py      # DebugBridgeNode：rclpy 订阅/发布封装
│   ├── config.py        # 面板配置（端口、话题映射）
│   ├── state.py         # 服务端状态缓冲与广播
│   ├── ws.py           # WebSocket 连接管理
│   └── routes.py       # REST API 路由
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    ├── tsconfig.json
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/
        │   ├── ws.ts
        │   └── http.ts
        ├── hooks/
        │   ├── useWebSocket.ts
        │   └── useRobotState.ts
        ├── components/
        │   ├── AsrInput.tsx
        │   ├── AgentOutput.tsx
        │   ├── DecisionTimeline.tsx
        │   ├── RobotStatus.tsx
        │   └── layout/
        │       ├── Header.tsx
        │       └── Panel.tsx
        └── types/
            └── index.ts
```

### 4.2 server.py — FastAPI + rclpy 生命周期

职责：启动 FastAPI 应用，在后台线程中 spin rclpy 节点，管理关闭，并维护 Web/ROS 两侧的线程边界。

```python
class DebugBridgeServer:
    def __init__(self):
        rclpy.init()
        self.state = PanelState()
        self.ws_manager = WebSocketManager()
        self.asr_publish_queue = queue.Queue()
        self.loop = None
        self.web_broadcast_queue = None
        self.ros_node = DebugBridgeNode(
            state=self.state,
            asr_publish_queue=self.asr_publish_queue,
            notify_web=self.notify_web_from_ros_thread,
        )

    async def startup(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.web_broadcast_queue = asyncio.Queue()
        self._broadcast_task = asyncio.create_task(self.broadcast_worker())
        self._spin_thread = threading.Thread(target=rclpy.spin, args=(self.ros_node.node,), daemon=True)
        self._spin_thread.start()

    def notify_web_from_ros_thread(self, message: dict) -> None:
        if self.loop is None or self.web_broadcast_queue is None:
            return
        self.loop.call_soon_threadsafe(self.web_broadcast_queue.put_nowait, message)

    async def broadcast_worker(self) -> None:
        while True:
            message = await self.web_broadcast_queue.get()
            await self.ws_manager.broadcast(message)

    def start(self):
        # FastAPI lifespan startup 初始化 asyncio 队列后再启动 ROS spin 线程
        uvicorn.run(self.app, host=self.config.host, port=self.config.port)
```

关键约束：

1. 所有 ROS2 publisher/subscription/timer 都在 `DebugBridgeNode` 内创建。
2. REST 路由不得直接调用 ROS publisher；`POST /api/asr/publish` 只把请求写入 `asr_publish_queue`，由 `DebugBridgeNode` 的 ROS timer drain queue 并发布 `/g1/audio/asr`。
3. ROS 订阅回调不得直接 await WebSocket broadcast；回调只更新线程安全 `PanelState`，再通过 `loop.call_soon_threadsafe()` 把消息送入 `web_broadcast_queue`。
4. WebSocket 连接集合只在 FastAPI asyncio event loop 内读写。
5. FastAPI lifespan startup 必须调用 `DebugBridgeServer.startup()`，确保 `loop` 和 `web_broadcast_queue` 绑定到实际运行的 event loop 后再启动 ROS spin 线程，避免早期 ROS 回调因 broadcast queue 未初始化而丢失 WebSocket 事件。
6. 默认 host 为 `127.0.0.1`。如果配置为 `0.0.0.0` 或其他非 loopback 地址，必须显式设置 `allow_remote: true`；否则启动失败。远程监听启动时必须打印 warning，提示该面板可发布 ASR 并可能触发机器人运动链路。
7. 关闭时先停止接受新 HTTP 请求，再停止 broadcast worker、ROS spin 线程，最后 destroy node 和 `rclpy.shutdown()`。

### 4.3 ros_node.py — DebugBridgeNode

封装所有 rclpy 订阅，将话题数据转换为统一的内部消息格式。

订阅的话题与数据处理：

| 话题 | 类型 | 处理 |
|------|------|------|
| `/g1/audio/asr` | String | 记录 ASR 事件到 timeline |
| `/voice/state` | String | 解析 JSON，更新 session 状态、last_decision、last_error |
| `/voice/debug/events` | String | 解析 voice_bridge 内部调试事件，驱动 AgentOutput 和决策 timeline |
| `/g1/state/mode` | String | 解析 JSON，更新 robot_mode 摘要；解析失败时保留 raw text 和 parse_error |
| `/g1/state/safety` | String | 解析 JSON，更新 safety_state 摘要；解析失败时保留 raw text 和 parse_error |
| `/g1/state/health` | DiagnosticArray | 更新 health 摘要 |
| `/voice/cmd/loco` | String | 记录运动命令到 timeline |
| `/voice/cmd/action` | String | 记录动作命令到 timeline |
| `/g1/cmd/audio/tts` | String | 记录 TTS 输出到 timeline |
| `/g1/cmd/audio/led` | String | 记录 LED 输出到 timeline |
| `/g1/safe_cmd/loco` | String | 记录安全验证后命令到 timeline |
| `/g1/safe_cmd/stop` | String | 记录安全验证后停止命令到 timeline |
| `/g1/safety/decisions` | String | 记录安全决策到 timeline |

提供的方法：

```python
class DebugBridgeNode:
    def publish_asr(self, text: str, confidence: float | None, is_final: bool) -> None:
        """将 ASR 事件发布到 /g1/audio/asr"""
```

ASR 发布请求处理：

- `/api/asr/publish` 接收 `{ text, confidence?, is_final?, source? }`，校验 `text` 非空、`confidence` 在 `[0, 1]`。
- 后端写入 `asr_publish_queue`，不直接跨线程 publish。
- `DebugBridgeNode` timer drain queue，构造 `std_msgs/msg/String`。`/api/asr/publish` 和 `/api/asr/quick` 都发布 JSON：`{ text, confidence, is_final, source, stamp }`；quick 使用 `defaults.asr_confidence`、`defaults.asr_is_final`、`defaults.asr_source`。

状态话题解析规则：

| 话题 | 解析字段 | UI 展示 |
|------|----------|---------|
| `/g1/state/mode` | `mode`, `control_owner`, `mode_source`, `sport_fsm_mode`, `sport_fsm_id`, `source` | RobotStatus 的 Mode 区域 |
| `/g1/state/safety` | `enabled`, `strict_mode`, `robot_state`, `last_decision`, `last_rejection_reason`, `allow_count`, `reject_count` | RobotStatus 的 Safety 区域 |
| `/voice/state` | `session`, `last_asr_text`, `last_decision`, `last_error`, `agent_backend` | Session、Last Error、Agent Backend |

解析失败不得丢弃原始消息；`PanelState` 保留 `{ raw, parse_error }`，状态面板显示 raw 摘要，timeline 记录 `parse_error` 事件。

健康状态归一化规则：

- `/g1/state/health` 使用 `diagnostic_msgs/msg/DiagnosticArray`。
- 后端将每个 `DiagnosticStatus` 转为 `{ name, level, message, values }`，保存在 `HealthState.raw.statuses`。
- `HealthState.max_level` 为所有 status 的最大 level；无 status 时为 `null`。
- `HealthState.summary` 映射：`null → "unknown"`，`0 → "ok"`，`1 → "warn"`，`2+ → "error"`。
- 如果超过 `state_timeout_ms` 未收到新的 health 消息，summary 显示 `"stale"`，并保留最后一次 raw。

#### `/voice/debug/events` 事件流

为避免调试面板从 `/voice/cmd/*`、TTS、LED 和 `/voice/state` 反推 agent 内部状态，voice_bridge 增加一个只读调试事件流：

- 话题：`/voice/debug/events`
- 类型：`std_msgs/msg/String`
- 负载：JSON
- 用途：仅供调试面板、日志和人工排障使用
- 约束：不得作为控制节点、安全节点或业务自动化的输入；不得替代 `/voice/state` 或 `/g1/safety/decisions`

事件基础结构：

```json
{
  "schema_version": "voice_debug_event.v1",
  "timestamp": 1751851200.0,
  "session_id": "20260707T083001.123456Z",
  "event": "agent_result",
  "data": {}
}
```

首版事件类型：

| event | 触发时机 | data |
|-------|----------|------|
| `asr_received` | voice_bridge 收到并解析 ASR 后 | `{ text, confidence, is_final, source, stamp }` |
| `session_decision` | wake word / stop word / ignore / agent 路由决策完成后 | `SessionDecision.to_dict()` |
| `agent_started` | agent 请求提交前 | `{ text, backend, robot_mode, safety_state }` |
| `agent_result` | agent 返回结果后、发布命令前 | `{ commands, reply_text, led, requires_confirmation }` |
| `agent_error` | agent 调用失败时 | `{ error, fallback_reply_text }` |
| `command_published` | voice_bridge 发布 loco/action/TTS/LED 后 | `{ topic, command_kind, payload }` |
| `agent_tool_event` | Pi agent 暴露工具调用事件时（可选） | `{ tool_name, phase, arguments?, result?, error? }` |

`agent_result` 示例：

```json
{
  "schema_version": "voice_debug_event.v1",
  "timestamp": 1751851200.42,
  "session_id": "20260707T083001.123456Z",
  "event": "agent_result",
  "data": {
    "commands": [{ "kind": "loco", "params": { "vx": 0.25, "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0 } }],
    "reply_text": "收到",
    "led": null,
    "requires_confirmation": false
  }
}
```

调试面板处理规则：

1. `/voice/debug/events` 是 AgentOutput 的主要数据源，尤其是 `agent_result`。
2. DecisionTimeline 将 debug 事件作为 voice_bridge 内部链路，将 `/g1/safety/decisions` 作为 safety_control 链路。
3. `/voice/cmd/*`、`/g1/cmd/audio/*` 和 `/g1/safe_cmd/*` 仍然订阅，用于核对实际发布结果和展示最终命令。
4. 如果 debug topic 暂不可用，面板可以降级为基于现有话题的 timeline，但 AgentOutput 必须标记为“推断结果”。
5. 如果没有 `agent_tool_event`，DecisionTimeline 在 agent 节点详情中显示“未提供工具事件”，不把空白解释为 agent 未调用工具。

voice_bridge 侧配套变更：

- `voice_bridge.config.DEFAULT_CONFIG["topics"]` 增加 `debug_events: /voice/debug/events`。这是 voice_bridge 包内配置键；debug panel 包内配置键保持 `voice_debug_events`，两者指向同一个 ROS topic。
- `VoiceBridgeConfig.validate()` 将 `debug_events` 纳入 required topics。
- `VoiceBridgeNode` 增加 `debug_pub`，在 ASR 解析、session decision、agent start/result/error、command publish 位置发布 debug 事件。
- debug 发布必须 best-effort，不允许因为 debug serialization 或 publish 失败影响 `/voice/cmd/*`、TTS、LED、`/voice/state` 的现有行为。
- 单元测试覆盖每类首版事件的 schema_version、event、timestamp、session_id、data 结构。

### 4.4 state.py — PanelState

线程安全的状态管理中心，维护所有话题的最新值和历史 timeline 事件。

```python
@dataclass
class TimelineEvent:
    timestamp: float
    source: str          # "asr" | "voice_state" | "cmd_loco" | "cmd_action" | ...
    kind: str            # 具体事件类型
    data: dict[str, Any]
    session_id: str | None = None

class PanelState:
    """线程安全的状态缓冲"""
    robot_mode: dict | None          # 解析后的 /g1/state/mode；失败时含 raw/parse_error
    safety_state: dict | None        # 解析后的 /g1/state/safety；失败时含 raw/parse_error
    health_summary: str | None
    voice_session: dict | None        # 来自 /voice/state 的 session snapshot
    last_asr_text: str | None
    last_decision: dict | None
    last_error: str | None
    timeline: list[TimelineEvent]     # 最近 N 条事件（N 默认 200）
    notify_web: Callable | None       # 线程安全通知函数；只负责把消息送入 broadcast queue

    def push_event(self, source: str, kind: str, data: dict) -> None:
        """添加 timeline 事件并通过 notify_web 入队 WebSocket 消息"""
```

### 4.5 ws.py — WebSocket 管理

```python
class WebSocketManager:
    connections: set[WebSocket]

    async def connect(self, ws: WebSocket) -> None
    async def disconnect(self, ws: WebSocket) -> None
    async def broadcast(self, message: dict) -> None
```

WebSocket 消息协议（服务端 → 客户端）：

```json
{
  "type": "robot_state",
  "data": {
    "robot_mode": {
      "data": {
        "mode": "sport_api_loco",
        "control_owner": "voice",
        "mode_source": "sport_api",
        "sport_fsm_mode": 1
      }
    },
    "safety_state": {
      "data": {
        "enabled": true,
        "strict_mode": true,
        "last_rejection_reason": null,
        "last_decision": null
      }
    },
    "health": {
      "summary": "ok",
      "max_level": 0,
      "status_count": 1,
      "raw": { "statuses": [{ "name": "g1_interface", "level": 0, "message": "ok", "values": {} }] }
    },
    "voice_session": { "state": "ACTIVE", "session_id": "..." }
  }
}
```

```json
{
  "type": "timeline_event",
  "data": {
    "timestamp": 1751851200.0,
    "source": "asr",
    "kind": "asr_received",
    "data": { "text": "小宇向前", "confidence": 0.95 },
    "session_id": null
  }
}
```

```json
{
  "type": "agent_result",
  "data": {
    "commands": [{ "kind": "loco", "params": { "vx": 0.25, ... } }],
    "reply_text": "收到",
    "led": null,
    "requires_confirmation": false,
    "session_id": "..."
  }
}
```

`agent_result` WebSocket 消息由 `/voice/debug/events` 的 `agent_result` 事件转换而来，不从 TTS/LED/命令话题反推。

### 4.6 routes.py — REST API

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/asr/publish` | 校验 body `{ text, confidence?, is_final?, source? }`，写入 ASR publish queue |
| POST | `/api/asr/quick` | 快捷发布，只传 text，其他用默认值，写入 ASR publish queue |
| GET | `/api/history` | 获取 timeline 历史记录，query: `?limit=50&offset=0` |
| GET | `/api/config` | 返回当前面板配置（话题映射等） |
| GET | `/api/state` | 返回当前完整状态快照（robot_mode, safety, session 等） |

## 5. 前端设计

### 5.1 页面布局

四面板网格布局，自适应窗口：

```text
┌─────────────────────────────────────────────────────────┐
│  Header: G1 Voice Bridge Debug Panel     [状态指示灯]   │
├────────────────────┬────────────────────────────────────┤
│  ASR 输入区         │  决策时间线                          │
│  ┌──────────────┐  │  ┌────────────────────────────────┐│
│  │ 文字输入      │  │  │ 08:30:01  ASR: "小宇向前"       ││
│  │              │  │  │   └─ wake word 检测 → activated  ││
│  ├──────────────┤  │  │ 08:30:01  Intent: agent 路由     ││
│  │ confidence □  │  │  │ 08:30:02  Agent: robot_walk     ││
│  │ is_final  □   │  │  │   └─ vx:0.25 vy:0 vyaw:0 1.0s ││
│  │ [发送 ASR]    │  │  │ 08:30:02  Safety: allowed      ││
│  └──────────────┘  │  │ 08:30:02  TTS: "收到"           ││
│                    │  └────────────────────────────────┘│
├────────────────────┼────────────────────────────────────┤
│  Agent 输出         │  机器人状态                          │
│  ┌──────────────┐  │  ┌────────────────────────────────┐│
│  │ commands:    │  │  │ Mode: sport_api_loco             ││
│  │  • loco      │  │  │ Safety: normal                   ││
│  │    vx: 0.25  │  │  │ Health: ok                       ││
│  │    vy: 0.0   │  │  │ Session: ACTIVE (id: ...)        ││
│  │    vyaw: 0.0  │  │  │ Last Error: null                 ││
│  │    dur: 1.0s  │  │  │ Agent Backend: pi_rpc            ││
│  │ reply: "收到" │  │  │ ROS2 Connection: ● connected     ││
│  └──────────────┘  │  └────────────────────────────────┘│
└────────────────────┴────────────────────────────────────┘
```

### 5.2 组件职责

#### AsrInput
- 文本输入框（支持多行）
- confidence 浮点输入（默认 0.9，范围 0-1）
- is_final 开关（默认 true）
- 可选：source 下拉（默认 "debug"）
- 「发送 ASR」按钮 + Enter 快捷键
- 「快捷发送」按钮（直接发纯文字，默认参数）

#### AgentOutput
- 显示最近一次 agent 决策结果，主要来源为 `/voice/debug/events` 的 `agent_result`
- commands 列表，按 kind 分色显示（loco=蓝, action=红, say=绿, led=紫）
- reply_text 展示
- requires_confirmation 标记
- 错误信息展示（红色高亮）

#### DecisionTimeline
- 垂直时间线，每个事件一个节点
- 事件类型图标/颜色区分：
  - ASR 接收：灰色圆点
  - Wake word 激活：绿色
  - Stop word：红色
  - Intent 路由：蓝色
  - Agent 决策：紫色
  - 命令发布（loco/action）：橙色
  - Safety 验证：黄/绿
  - TTS/LED 输出：青色
- 每个节点可展开查看详细 JSON 数据
- 自动滚动到最新事件
- 自动清除旧事件（保留最近 200 条）

#### RobotStatus
- robot_mode 指示灯（green=idle, yellow=moving, red=fault）
- safety_state 指示灯（基于 parsed JSON 的 `enabled`、`strict_mode`、`last_rejection_reason`、`last_decision`）
- health 状态摘要
- `/g1/state/mode` 解析字段：mode、control_owner、mode_source、sport_fsm_mode、sport_fsm_id
- `/g1/state/safety` 解析字段：enabled、strict_mode、robot_state、last_decision、last_rejection_reason、allow_count、reject_count
- JSON 解析失败时显示 raw 摘要和 parse_error
- voice_bridge session 信息（state, session_id, started_sec, last_activity_sec）
- last_error 显示
- agent_backend 类型
- WebSocket 连接状态指示
- ROS2 节点连接状态指示

### 5.3 TypeScript 类型

```typescript
// WebSocket 消息
interface WsMessage {
  type: "robot_state" | "timeline_event" | "agent_result" | "connection_status";
  data: RobotState | TimelineEvent | AgentResult | ConnectionStatus;
}

interface RobotState {
  robot_mode: RobotModeState | null;
  safety_state: SafetyState | null;
  health: HealthState | null;
  voice_session: VoiceSession | null;
  last_asr_text: string | null;
  last_decision: Record<string, unknown> | null;
  last_error: string | null;
  agent_backend: string | null;
}

interface VoiceSession {
  state: "IDLE" | "ACTIVE" | "AGENT_PENDING";
  session_id: string | null;
  started_sec: number | null;
  last_activity_sec: number | null;
}

interface ParsedTopicState<T extends Record<string, unknown>> {
  raw?: string;
  parse_error?: string;
  data?: T;
}

interface RobotModeFields {
  mode?: string | null;
  control_owner?: string | null;
  mode_source?: string | null;
  sport_fsm_mode?: number | null;
  sport_fsm_id?: number | null;
  source?: string | null;
}

type RobotModeState = ParsedTopicState<RobotModeFields>;

interface SafetyFields {
  enabled?: boolean;
  strict_mode?: boolean;
  robot_state?: Record<string, unknown>;
  last_decision?: Record<string, unknown> | null;
  last_rejection_reason?: string | null;
  allow_count?: number;
  reject_count?: number;
}

type SafetyState = ParsedTopicState<SafetyFields>;

interface HealthState {
  summary: "ok" | "warn" | "error" | "stale" | "unknown";
  max_level: number | null;
  status_count: number;
  raw: Record<string, unknown> | null;
}

interface ConnectionStatus {
  websocket: "connecting" | "connected" | "reconnecting" | "disconnected";
  ros_node: "unknown" | "ready" | "stale" | "error";
  last_message_at: number | null;
  reconnect_attempt: number;
  error: string | null;
}

interface TimelineEvent {
  timestamp: number;
  source: string;
  kind: string;
  data: Record<string, unknown>;
  session_id: string | null;
}

interface AgentResult {
  commands: AgentCommand[];
  reply_text: string | null;
  led: Record<string, unknown> | null;
  requires_confirmation: boolean;
  session_id: string | null;
}

interface AgentCommand {
  kind: string;
  params: Record<string, unknown>;
}
```

### 5.4 状态管理

使用 React Context + useReducer，不引入 Redux 等外部库：

```
AppContext
  ├── robotState: RobotState           // 由 WebSocket robot_state 消息更新
  ├── timeline: TimelineEvent[]      // 由 WebSocket timeline_event 消息追加
  ├── agentResult: AgentResult | null // 由 WebSocket agent_result 消息更新
  └── connectionStatus: ConnectionStatus
```

### 5.5 WebSocket 重连策略

- 连接断开时自动重连，指数退避（1s → 2s → 4s → ... → 30s max）
- 重连成功后，调用 GET `/api/state` 和 GET `/api/history` 恢复状态
- UI 上显示连接状态（Header 状态指示灯）

### 5.6 开发代理

开发模式下浏览器访问 Vite dev server `http://localhost:5173`，后端默认监听 `http://127.0.0.1:8765`。为避免 CORS 和 WebSocket origin 差异，Vite 配置代理：

```typescript
// vite.config.ts
server: {
  proxy: {
    "/api": "http://127.0.0.1:8765",
    "/ws": {
      target: "ws://127.0.0.1:8765",
      ws: true
    }
  }
}
```

前端 HTTP 和 WebSocket 客户端默认使用相对路径 `/api/...` 和 `/ws`。生产模式由 FastAPI 同源服务静态文件、REST API 和 WebSocket。

## 6. 启动方式

### 开发模式

```bash
# 终端 1：启动后端
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
cd /home/ubuntu/Desktop/unitree_g1_agent
colcon build --packages-select voice_bridge_debug
source install/setup.bash
ros2 run voice_bridge_debug debug_panel_server

# 终端 2：启动前端 dev server
cd src/voice_bridge_debug/frontend
npm install
npm run dev
# 浏览器打开 http://localhost:5173
```

### 生产模式

```bash
# 构建前端
cd src/voice_bridge_debug/frontend
npm run build

# 单进程启动（FastAPI serve 静态文件）
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
source install/setup.bash
ros2 run voice_bridge_debug debug_panel_server -- --prod
# 浏览器打开 http://localhost:8765
```

### Python 包入口与静态文件

`setup.py` 必须定义 console script：

```python
entry_points={
    "console_scripts": [
        "debug_panel_server=voice_bridge_debug.server:main",
    ],
}
```

生产模式下 FastAPI 从 `voice_bridge_debug/frontend_dist/` 或 package data 中的等价目录服务 Vite 构建产物。`npm run build` 的输出需要在打包/安装步骤中复制到该静态目录；如果静态目录缺失，`--prod` 启动必须失败并给出明确错误。

### ROS2 Launch 集成

```python
# launch/debug_panel.launch.py
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='voice_bridge_debug',
            executable='debug_panel_server',
            name='voice_bridge_debug_node',
            output='screen',
            parameters=[{'host': '127.0.0.1', 'port': 8765}],
        ),
    ])
```

## 7. 配置

```yaml
# voice_bridge_debug/config/debug_panel.yaml
server:
  host: "127.0.0.1"
  port: 8765
  allow_remote: false

topics:
  asr: /g1/audio/asr
  voice_state: /voice/state
  voice_debug_events: /voice/debug/events
  robot_mode: /g1/state/mode
  safety_state: /g1/state/safety
  health: /g1/state/health
  voice_cmd_loco: /voice/cmd/loco
  voice_cmd_action: /voice/cmd/action
  tts: /g1/cmd/audio/tts
  led: /g1/cmd/audio/led
  safe_cmd_loco: /g1/safe_cmd/loco
  safe_cmd_stop: /g1/safe_cmd/stop
  safety_decisions: /g1/safety/decisions

defaults:
  asr_confidence: 0.9
  asr_is_final: true
  asr_source: "debug"

timeline:
  max_events: 200

asr_default_text: "小宇"
```

`allow_remote` 只控制是否允许非 loopback 监听；不提供认证能力。`host` 为 `127.0.0.1` 或 `localhost` 时可保持 `false`。`host` 为 `0.0.0.0`、局域网 IP 或其他非 loopback 地址时必须显式设为 `true`。

配置命名约定：`voice_bridge` 包内使用 `topics.debug_events`，`voice_bridge_debug` 包内使用 `topics.voice_debug_events`。两个配置键名称不同，但默认值都指向同一个 ROS topic `/voice/debug/events`。

## 8. 依赖

### Python (后端)

- `fastapi` >= 0.100
- `uvicorn[standard]` >= 0.20
- `websockets` (FastAPI 内置依赖)
- `pyyaml` (已有)
- `rclpy` (ROS2 Humble，系统级)

### Node.js (前端)

- `react` ^18
- `react-dom` ^18
- `vite` ^5
- `typescript` ^5
- `tailwindcss` ^3
- `@types/react` ^18
- `@types/react-dom` ^18
- `autoprefixer`
- `postcss`

## 9. 测试策略

### 后端单元测试

- `PanelState` ring buffer：超过 `timeline.max_events` 后保留最近 N 条。
- JSON 解析：`/voice/state`、`/g1/state/mode`、`/g1/state/safety` 正常解析；非法 JSON 保留 raw 和 parse_error。
- Health 归一化：DiagnosticArray level 映射为 `ok/warn/error/unknown/stale`，并保留 max_level、status_count、raw.statuses。
- ASR REST 校验：空 text 拒绝；confidence 超出 `[0, 1]` 拒绝；合法请求进入 `asr_publish_queue`。
- ROS timer drain：从 `asr_publish_queue` 构造 JSON `std_msgs/msg/String`，发布到配置的 ASR topic；`/api/asr/quick` 使用默认 confidence/is_final/source。
- Web broadcast：ROS 回调通过 `notify_web_from_ros_thread()` 入队，`broadcast_worker()` 在 asyncio loop 内调用 `WebSocketManager.broadcast()`。
- `/voice/debug/events` 转换：`agent_result` debug 事件生成 WebSocket `agent_result` 消息，其他 debug 事件生成 timeline_event。

### voice_bridge 单元测试

- 新增 `debug_events` topic 配置校验。
- ASR 解析后发布 `asr_received` 和 `session_decision`。
- agent 调用前发布 `agent_started`。
- agent 成功后发布 `agent_result`，且在 command publish 前发生。
- agent 失败后发布 `agent_error`，且不发布运动命令。
- 每次 loco/action/TTS/LED publish 后发布 `command_published`。

### 前端测试

- WebSocket reducer 正确处理 `robot_state`、`timeline_event`、`agent_result`、`connection_status`。
- ConnectionStatus 覆盖 connecting、connected、reconnecting、disconnected 和 ros_node ready/stale/error 状态。
- RobotStatus 展示 parsed JSON 字段；parse_error 时展示 raw 摘要。
- DecisionTimeline 在没有 `agent_tool_event` 时显示“未提供工具事件”。
- WebSocket 重连成功后调用 `/api/state` 和 `/api/history` 恢复状态。
- Vite dev proxy 将 `/api` 和 `/ws` 转发到 `127.0.0.1:8765`，前端客户端使用相对路径。

### 手工验证

- `ros2 topic echo /voice/debug/events` 能看到 `voice_debug_event.v1` 事件。
- `ros2 topic echo /g1/safe_cmd/stop` 能在 stop/cancel 流程中看到安全后停止命令。
- 默认启动只监听 `127.0.0.1:8765`；非 loopback host 未设置 `allow_remote: true` 时启动失败；远程监听配置会打印 warning。

## 10. 不做的事（YAGNI）

- **不做**音频录制/ASR 识别（只做文字输入）
- **不做**对话历史持久化到磁盘（只在内存中保留 timeline）
- **不做**命令发送功能（只发送 ASR 模拟事件，不直接发运动命令）
- **不做**多用户/认证（本地开发工具，单用户；默认只绑定 `127.0.0.1`）
- **不做**图表可视化（用状态指示灯和文本，不引入 Chart.js 等）
- **不做**g1_sim 集成（调试面板是被动监听，不启动仿真器）
- **不做**多个分散的 voice_bridge debug topic（只保留 `/voice/debug/events` 一个只读事件流）

## 11. 验收标准

- [ ] 启动后端，浏览器打开页面，看到四个面板
- [ ] 使用 `rule_based` agent 和默认 motion 配置，在 ASR 输入区输入 "小宇向前"，点击发送
- [ ] DecisionTimeline 显示：ASR 接收 → wake word 检测 → agent 路由 → agent 决策 → 命令发布
- [ ] DecisionTimeline 中 voice_bridge 内部链路来自 `/voice/debug/events`，安全验证链路来自 `/g1/safety/decisions`
- [ ] AgentOutput 显示 loco command（vx:0.25, vy:0, vyaw:0, dur:1.0s）
- [ ] AgentOutput 的 commands/reply_text/led/requires_confirmation 来自 `agent_result` debug 事件
- [ ] 输入 stop/cancel 词后，DecisionTimeline 显示 `/voice/cmd/action` → `/g1/safety/decisions` → `/g1/safe_cmd/stop`
- [ ] RobotStatus 显示 session 状态从 IDLE → ACTIVE 变化
- [ ] RobotStatus 正确展示 `/g1/state/mode` 和 `/g1/state/safety` 的 JSON 字段；非法 JSON 显示 parse_error 和 raw 摘要
- [ ] WebSocket 断开后自动重连，恢复状态
- [ ] 默认后端监听 `127.0.0.1:8765`；非 loopback host 未设置 `allow_remote: true` 时启动失败；配置远程监听时启动日志出现安全 warning
- [ ] 生产模式下 `npm run build` + 单进程启动正常工作
