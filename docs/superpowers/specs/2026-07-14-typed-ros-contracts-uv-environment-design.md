# G1 强类型 ROS 契约与 uv 环境设计

## 1. 目标

本阶段建立 `g1_agent_msgs`，把语音到运动执行的核心 ROS 2 topic 从
`std_msgs/msg/String` 加 JSON 原地切换为强类型消息，同时统一项目的 Python
与测试环境。

完成后，以下链路只使用 ROS 2 强类型消息：

```text
asr_node / g1_interface
  -> voice_bridge
  -> safety_control
  -> g1_interface
  -> Unitree Sport API
```

JSON 只保留在以下边界：

- Unitree 原生 `/audio_msg` 和 Sport API `parameter`；
- Pi RPC、HTTP 和其他外部 agent transport；
- WebSocket、调试事件和结构化日志。

本阶段的唯一开发和 CI 基线是 Ubuntu 22.04、ROS 2 Humble 和 Python 3.10。

## 2. 范围

### 2.1 包含

- 新增 `g1_agent_msgs` ROS 2 接口包；
- 定义 8 个消息类型；
- 原地迁移核心 topic，不提供 JSON 双发布；
- 迁移 `asr_node`、`voice_bridge`、`safety_control`、`g1_interface` 和
  `voice_bridge_debug`；
- 使用 `uv` 创建并锁定 Python 3.10 项目环境；
- 提供统一的 Makefile 命令和 CI 入口；
- 增加强类型 happy path 与 stop path 集成测试；
- 更新数据契约和开发文档。

### 2.2 不包含

- 完整的多节点故障注入矩阵；
- `g1_bringup`、sim/real/safe-debug/no-agent profiles；
- Pi 可执行文件和扩展目录的可移植性改造；
- ASR lifecycle、离线 Silero VAD 模型管理；
- 大节点拆分和完整结构化指标体系。

这些项目在本阶段完成后分别进入独立设计和实施周期。

## 3. 设计原则

1. `g1_agent_msgs` 中的 `.msg` 是 ROS topic 的唯一权威契约。
2. 同一仓库内生产者和消费者在一个迁移阶段内全部切换。
3. 消息类型负责结构约束，安全节点继续负责语义和策略校验。
4. 缺失数值通过 `has_*` 字段表达，不使用 `null` 或魔术数。
5. 时间使用 `builtin_interfaces/Time`，时长使用
   `builtin_interfaces/Duration`。
6. 线速度单位为 `m/s`，角速度为 `rad/s`，温度为摄氏度，电压为伏特。
7. 可变调试详情不进入核心消息，通过 diagnostics、WebSocket 或日志输出。
8. ROS 包不依赖用户目录下的 Python site-packages。

## 4. 接口包

新增 `src/g1_agent_msgs`，使用 `ament_cmake` 和
`rosidl_default_generators`。接口包包含：

```text
src/g1_agent_msgs/
  CMakeLists.txt
  package.xml
  msg/
    VoiceEvent.msg
    LocoIntent.msg
    ActionIntent.msg
    RobotStateSummary.msg
    SafetyDecision.msg
    ValidatedLocoCommand.msg
    ValidatedActionCommand.msg
    SafetyStatus.msg
```

依赖包括：

- `builtin_interfaces`；
- `geometry_msgs`；
- `rosidl_default_generators`；
- `rosidl_default_runtime`。

## 5. 消息模型

### 5.1 VoiceEvent

`VoiceEvent` 表示内部 ASR 和已识别的音频状态事件。

| 字段 | 类型 | 语义 |
|---|---|---|
| `stamp` | `builtin_interfaces/Time` | 事件时间 |
| `source` | `string` | `builtin_asr`、`custom_asr`、`debug` 等来源 |
| `event_type` | `string` | 使用消息常量，至少包含 `asr`、`playback` |
| `has_sequence_id` | `bool` | `sequence_id` 是否有效 |
| `sequence_id` | `uint64` | 原生音频事件序号 |
| `text` | `string` | ASR 文本；非文本事件为空 |
| `has_confidence` | `bool` | `confidence` 是否有效 |
| `confidence` | `float32` | ASR 置信度，范围 `[0, 1]` |
| `is_final` | `bool` | 是否为最终 ASR 结果 |
| `language` | `string` | BCP 47 风格语言标识；未知时为空 |
| `has_playback_state` | `bool` | `playback_state` 是否有效 |
| `playback_state` | `int8` | 使用 stopped/playing 消息常量 |

Unitree `/audio_msg` 的未知或非法载荷不得原样转发为内部 JSON。已识别事件转换为
`VoiceEvent`；不支持或非法载荷只记录调试日志并更新 diagnostics 计数。

### 5.2 LocoIntent

| 字段 | 类型 | 语义 |
|---|---|---|
| `created_at` | `builtin_interfaces/Time` | 命令创建时间 |
| `source` | `string` | 命令生产者 |
| `session_id` | `string` | 会话 ID，可为空 |
| `command_id` | `string` | 非空且在控制链中稳定的命令 ID |
| `text` | `string` | 触发命令的原始文本，可为空 |
| `vx` | `float64` | 前向线速度，`m/s` |
| `vy` | `float64` | 侧向线速度，`m/s` |
| `vyaw` | `float64` | 偏航角速度，`rad/s` |
| `duration` | `builtin_interfaces/Duration` | 命令持续时间 |

### 5.3 ActionIntent

| 字段 | 类型 | 语义 |
|---|---|---|
| `created_at` | `builtin_interfaces/Time` | 命令创建时间 |
| `source` | `string` | 命令生产者 |
| `session_id` | `string` | 会话 ID，可为空 |
| `command_id` | `string` | 非空命令 ID |
| `text` | `string` | 触发命令的原始文本，可为空 |
| `action` | `string` | 使用 `stop`、`cancel` 等消息常量 |
| `priority` | `string` | 使用 `normal`、`emergency` 等消息常量 |

### 5.4 RobotStateSummary

`RobotStateSummary` 同时承载 `/g1/state/low`、`/g1/state/mode` 和安全决策快照。
不适用于完整电机数组；`/g1/state/motors` 在后续状态消息设计中单独迁移。

| 字段 | 类型 | 语义 |
|---|---|---|
| `stamp` | `builtin_interfaces/Time` | 状态采样或快照时间 |
| `source` | `string` | `lowstate`、`lf/lowstate` 或安全快照来源 |
| `mode` | `string` | 使用 mode 消息常量；未知值允许保留 |
| `control_owner` | `string` | `internal`、`user` 或 `unknown` |
| `mode_source` | `string` | 模式判断来源 |
| `has_sport_fsm_mode` | `bool` | FSM mode 是否有效 |
| `sport_fsm_mode` | `int32` | Sport FSM mode |
| `has_sport_fsm_id` | `bool` | FSM ID 是否有效 |
| `sport_fsm_id` | `int32` | Sport FSM ID |
| `rpy` | `geometry_msgs/Vector3` | roll/pitch/yaw，`rad` |
| `orientation` | `geometry_msgs/Quaternion` | 机器人姿态 |
| `angular_velocity` | `geometry_msgs/Vector3` | IMU 角速度，`rad/s` |
| `linear_acceleration` | `geometry_msgs/Vector3` | IMU 线加速度，`m/s^2` |
| `motor_count` | `uint32` | 电机数量 |
| `has_max_temperature` | `bool` | 最大温度是否有效 |
| `max_temperature_c` | `float32` | 最大电机温度，摄氏度 |
| `has_battery_voltage` | `bool` | 电池电压是否有效 |
| `battery_voltage` | `float32` | 电池电压，伏特 |
| `velocity` | `geometry_msgs/Twist` | 当前或最近命令速度 |
| `velocity_source` | `string` | 速度来源 |
| `health_state` | `string` | `ok`、`degraded`、`unhealthy` 或 `unknown` |
| `has_lowstate_age` | `bool` | lowstate age 是否有效 |
| `lowstate_age` | `builtin_interfaces/Duration` | lowstate 新鲜度年龄 |

### 5.5 SafetyDecision

| 字段 | 类型 | 语义 |
|---|---|---|
| `stamp` | `builtin_interfaces/Time` | 决策完成时间 |
| `command_id` | `string` | 被验证命令 ID；解析前失败时为空 |
| `command_kind` | `string` | `loco` 或 `action` 常量 |
| `decision` | `string` | `allow` 或 `reject` 常量 |
| `reason` | `string` | 拒绝原因；允许时为空 |
| `validation_latency` | `builtin_interfaces/Duration` | 验证耗时 |
| `robot_state` | `RobotStateSummary` | 验证时使用的状态快照 |

动态 `check_details` 不进入该消息。稳定的拒绝原因使用明确字符串，计数和附加上下文
通过 diagnostics 与调试事件输出。

### 5.6 ValidatedLocoCommand

| 字段 | 类型 | 语义 |
|---|---|---|
| `intent` | `LocoIntent` | 原始运动意图 |
| `validated_at` | `builtin_interfaces/Time` | 验证时间 |
| `validation` | `SafetyDecision` | 必须为 allow 的验证结果 |

### 5.7 ValidatedActionCommand

| 字段 | 类型 | 语义 |
|---|---|---|
| `intent` | `ActionIntent` | 原始动作意图 |
| `validated_at` | `builtin_interfaces/Time` | 验证时间 |
| `validation` | `SafetyDecision` | 必须为 allow 的验证结果 |

该消息用于安全 stop/cancel 通道。`g1_interface` 必须同时检查 allow 和 action 类型，
但不得用 stale lowstate、mode 或 safety heartbeat 阻止 stop/cancel。

### 5.8 SafetyStatus

| 字段 | 类型 | 语义 |
|---|---|---|
| `stamp` | `builtin_interfaces/Time` | safety heartbeat 时间 |
| `node_name` | `string` | 固定为 `safety_control` |
| `enabled` | `bool` | safety_control 是否启用 |
| `strict_mode` | `bool` | 是否启用严格策略 |
| `robot_state` | `RobotStateSummary` | 当前安全状态快照 |
| `allow_count` | `uint64` | 累计允许数 |
| `reject_count` | `uint64` | 累计拒绝数 |
| `rejection_rate` | `float64` | 拒绝比例，范围 `[0, 1]` |
| `last_rejection_reason` | `string` | 最后拒绝原因；没有时为空 |
| `has_last_decision` | `bool` | `last_decision` 是否有效 |
| `last_decision` | `SafetyDecision` | 最近一次决策 |

## 6. Topic 映射

| Topic | 当前类型 | 目标类型 |
|---|---|---|
| `/g1/audio/asr` | `std_msgs/String` | `g1_agent_msgs/VoiceEvent` |
| `/g1/audio/event` | `std_msgs/String` | `g1_agent_msgs/VoiceEvent` |
| `/voice/cmd/loco` | `std_msgs/String` | `g1_agent_msgs/LocoIntent` |
| `/voice/cmd/action` | `std_msgs/String` | `g1_agent_msgs/ActionIntent` |
| `/g1/state/low` | `std_msgs/String` | `g1_agent_msgs/RobotStateSummary` |
| `/g1/state/mode` | `std_msgs/String` | `g1_agent_msgs/RobotStateSummary` |
| `/g1/safe_cmd/loco` | `std_msgs/String` | `g1_agent_msgs/ValidatedLocoCommand` |
| `/g1/safe_cmd/stop` | `std_msgs/String` | `g1_agent_msgs/ValidatedActionCommand` |
| `/g1/safety/decisions` | `std_msgs/String` | `g1_agent_msgs/SafetyDecision` |
| `/g1/state/safety` | `std_msgs/String` | `g1_agent_msgs/SafetyStatus` |

`/g1/state/health` 保持 `diagnostic_msgs/DiagnosticArray`。`/g1/state/imu` 保持
`sensor_msgs/Imu`。Unitree 原生 `/audio_msg` 保持 `std_msgs/String`。

## 7. 节点迁移

### 7.1 asr_node

- 直接发布 `VoiceEvent`；
- 将现有时间、来源、文本、置信度和 final 状态映射为字段；
- 不再生成内部 ASR JSON。

### 7.2 g1_interface

- 将 Unitree 原生 audio JSON 解析并映射为 `VoiceEvent`；
- 发布 `RobotStateSummary` 到 low 和 mode topic；
- 订阅 `SafetyStatus` 作为 watchdog heartbeat；
- 订阅两种 validated command；
- 只执行 allow 的 validated command；
- 保持 Sport API `parameter` JSON，因为该格式属于 Unitree 外部接口；
- 保持本地 deadline、命令确认、shutdown stop 和 stale-state stop 语义不变。

### 7.3 voice_bridge

- 直接消费 `VoiceEvent`；
- 会话和 agent 业务逻辑可以保留小型内部 dataclass；
- 发布 `LocoIntent` 和 `ActionIntent`；
- Pi/HTTP RPC 继续使用 JSON，但非法工具参数不得生成 intent；
- `/voice/state` 和 `/voice/debug/events` 继续作为调试 JSON topic，不参与运动授权。

### 7.4 safety_control

- 从消息字段直接构造验证输入，不解析 JSON；
- 继续检查 command ID、有限数值、时间新鲜度、速度范围、持续时间、模式、
  rate limit 和速度连续性；
- 允许的 loco 发布 `ValidatedLocoCommand`；
- 允许的 stop/cancel 发布 `ValidatedActionCommand`；
- 所有可审计决策发布 `SafetyDecision`；
- 周期性发布 `SafetyStatus`。

### 7.5 voice_bridge_debug

- 调试注入发布 `VoiceEvent`；
- 订阅所有已迁移的强类型 topic；
- 在 ROS adapter 中将消息转换为普通字典；
- WebSocket 和 HTTP 层继续使用 JSON；
- 不把 Web 输入中的任意 JSON 直接透传到运动 topic。

## 8. 错误处理

- ROS 消息生成保证字段存在，但不保证语义有效；安全校验仍是必须步骤。
- 空 `command_id`、非有限速度、非法 duration、过期命令和未知 action 被拒绝。
- 无法解析的 Unitree audio 载荷被丢弃，并通过 diagnostics 和调试日志记录。
- agent 输出解析失败、未知工具或非法参数时不发布 intent。
- `g1_interface` 收到 reject validated command、命令种类不匹配或非 stop/cancel
  的安全停止消息时拒绝执行并更新 diagnostics。
- stop、watchdog stop 和 shutdown stop 不依赖 fresh lowstate、mode 或 heartbeat。
- 迁移期间不运行 JSON 与强类型双 topic，避免重复命令和去重歧义。

## 9. uv 环境

### 9.1 基线

- 操作系统：Ubuntu 22.04；
- ROS：ROS 2 Humble；
- Python：`/usr/bin/python3` 3.10；
- 环境管理器：`uv 0.11.26`；
- 项目环境目录：`.venv-ros`。

创建环境：

```bash
uv venv --python /usr/bin/python3 --system-site-packages .venv-ros
UV_PROJECT_ENVIRONMENT=.venv-ros uv sync --frozen
```

使用 `--system-site-packages` 是为了访问 ROS Humble 通过 apt 安装的 `rclpy`、
launch 和消息生成模块。所有项目命令同时设置：

```bash
PYTHONNOUSERSITE=1
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
```

因此 `/usr/lib/python3/dist-packages` 可见，而 `~/.local/lib/python3.10/site-packages`
不可见。

### 9.2 pyproject.toml 与 uv.lock

根目录 `pyproject.toml`：

- 设置 `requires-python = "==3.10.*"`；
- 设置 `tool.uv.package = false`，根目录只管理工作区环境，不构建 Python 包；
- 使用精确 `==` 版本声明非 ROS 运行时直接依赖；
- 声明 `test`、`lint` 和 debug panel 依赖组；
- 固定 pytest、ruff 和 pyright 配置；
- 为 FastAPI、Starlette 和 HTTPX 声明匹配的直接版本。

`uv.lock` 锁定完整传递依赖。CI 和 Makefile 只使用 `uv sync --frozen`，锁文件与
`pyproject.toml` 不一致时立即失败。

ROS apt 包不写入 `uv.lock`，由 Ubuntu 22.04 和 ROS Humble 基线固定。

### 9.3 flake.nix

移除将 `pytest` 包装为 `/usr/bin/python3 -m pytest` 的脚本。Nix shell 继续提供
Unitree SDK、Unitree ROS 2 包和系统构建工具，但 Python 依赖由 `uv` 管理。

## 10. 统一命令

根目录 Makefile 提供：

| 命令 | 行为 |
|---|---|
| `make bootstrap` | 检查 Python 3.10 和 uv 0.11.26，创建 `.venv-ros`，执行 frozen sync |
| `make build` | source ROS Humble 后执行完整 `colcon build --symlink-install` |
| `make test` | 构建接口后运行全部 Python 单元测试和 ROS 包测试 |
| `make test-integration` | 运行强类型 happy path 与 stop path launch test |
| `make lint` | 运行 ruff 和 pyright |
| `make frontend` | 执行 `npm ci`、TypeScript/Vite build，并校验发布产物 |

Makefile 和 CI 不调用 Python 3.11 `.venv`，也不依赖用户安装的 pytest 插件。

## 11. 测试策略

### 11.1 接口测试

- `colcon build --packages-select g1_agent_msgs` 成功；
- Python 可从安装空间导入全部 8 个消息；
- `ros2 interface show` 可展示全部字段和常量；
- duration、time、可选字段和嵌套消息转换测试通过。

### 11.2 节点单元测试

- ASR 事件转换；
- voice intent 生成；
- safety allow/reject 和边界条件；
- robot state tracker 的强类型更新；
- validated command 执行门控；
- stop/cancel 无条件安全通道；
- safety heartbeat 与 watchdog；
- debug panel 消息字典转换。

### 11.3 集成测试

本阶段提供最小 `launch_testing` 链路：

1. 发布最终 ASR `VoiceEvent`；
2. 观察 `LocoIntent`；
3. 提供 fresh `RobotStateSummary` 和健康 diagnostics；
4. 观察 allow 的 `ValidatedLocoCommand`；
5. 观察对应 Sport API request；
6. 发布 stop `ActionIntent`；
7. 观察 validated stop 和零速度 Sport API request。

完整 lowstate 中断、Sport response 丢失、乱序、崩溃和超时矩阵属于下一阶段。

### 11.4 前端测试

- `npm ci` 使用已提交 lockfile；
- TypeScript 和 Vite build 成功；
- 构建脚本更新 `frontend_dist`；
- CI 对构建前后 git diff 进行检查，防止源码与发布产物漂移。

## 12. CI

CI 使用 Ubuntu 22.04 和 ROS 2 Humble，安装固定版本 uv，然后依次执行：

```text
make bootstrap
make build
make test
make test-integration
make frontend
make lint
```

CI 不直接复制 Makefile 中的环境变量、Python 路径或测试文件列表。

## 13. 文档

- 将 `docs/data_contracts.md` 改为强类型 topic 契约；
- 记录每个字段的单位、必填语义、有效范围和常量；
- 更新各包 README 中的测试命令；
- 根 README 的完整快速启动流程在 bringup 阶段补齐；本阶段只记录统一开发命令。

## 14. 验收标准

1. 8 个接口可以在 ROS Humble 安装空间生成和导入。
2. 第 6 节列出的核心 topic 不再使用 `std_msgs/String`。
3. 核心消息中不存在 JSON、通用 key/value 或 raw payload 兜底字段。
4. 强类型 happy path 和 stop path 集成测试通过。
5. 现有 watchdog、shutdown stop、状态新鲜度、速率和运动限制测试通过。
6. 调试面板可以消费新消息并完成前端构建。
7. `uv sync --frozen` 和全部 Makefile 验证命令通过。
8. CI 不读取用户 site-packages，也不使用 Python 3.11 ROS 环境。
9. `docs/data_contracts.md` 与实际 `.msg` 文件一致。

## 15. 后续阶段顺序

1. 移除 Pi 主机路径和仓库布局硬编码，安装扩展 package data 并发布依赖 diagnostics；
2. 新建 `g1_bringup`，提供 sim、real、safe-debug 和 no-agent profiles；
3. 基于强类型契约扩展完整闭环故障测试矩阵；
4. 完成 ASR 离线模型、lifecycle、指标和大节点拆分。
