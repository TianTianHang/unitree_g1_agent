# ROS 2 Foxy 实机适配与修复计划

**制定日期**：2026-07-21

**目标分支**：`main`

**实测参考分支**：`wip-changes`（提交 `a2db955`）

**当前主线基线**：`main`（提交 `68a822e`）

## 1. 目标

将项目的真实机器人运行基线从 ROS 2 Humble/Python 3.10 调整为机器人实际使用的 ROS 2 Foxy/Python 3.8，并在该环境中修复、验证以下关键链路：

1. CycloneDDS 与 Unitree 原生话题通信；
2. `g1_interface` 对 Unitree Sport API 的请求与响应匹配；
3. `official_loco` 后端的状态读取、模式查询、速度控制和停止保护；
4. 安全控制、语音桥接及后续 TextOp 接入。

本计划不直接认定实测机器上的 TextOp 模型路径、模型文件或哈希值存在问题。模型下载与部署作为独立阶段处理，不阻塞基础 ROS 和 Sport API 链路修复。

## 2. 已确认的问题

### 2.1 ROS 和 Python 基线不一致

`wip-changes` 已将 Makefile 的 ROS 路径改为 `/opt/ros/foxy`，并尝试使用 Python 3.8，但仓库其余配置仍包含以下 Humble/Python 3.10 约束：

- `pyproject.toml` 与 `uv.lock` 要求 Python 3.10；
- Ruff、Pyright 以 Python 3.10 为目标；
- `flake.nix` 和 `nix/pkgs/unitree-ros2.nix` 指向 Humble；
- README、设计文档和实机清单仍包含 Humble 命令；
- 部分依赖版本尚未确认是否支持 Python 3.8。

因此不能只修改 `source /opt/ros/...`，必须在 Foxy 环境中重新验证依赖、构建和运行入口。

### 2.2 Sport API 请求 ID 不符合 Unitree 官方实现

当前 `g1_interface` 使用从 1 开始递增的请求 ID。Unitree 官方 ROS 2 `BaseClient` 使用 `CLOCK_MONOTONIC` 的系统运行时间纳秒值作为 `header.identity.id`，并严格使用该 ID 匹配响应。

`wip-changes` 增加了按 `api_id` 匹配未完成请求的兜底逻辑，但这不能替代正确的请求 ID；连续存在多个相同 `api_id` 的请求时，可能把响应归属到错误请求。

目标实现：

- 使用 Python `time.monotonic_ns()` 生成请求 ID；
- 保证同一进程内 ID 单调且不重复；
- 响应严格按 `identity.id` 匹配；
- `api_id` 仅用于协议校验和诊断，不用于替代 ID 匹配。

### 2.3 DDS 配置不可靠

当前 `cyclone_ds_lo.xml` 含非 ASCII 弯引号，XML 无法解析；实测分支同时出现 `eth0` 和 `enp3s0` 两种网卡名。DDS 配置需要根据实际机器人网络接口生成或通过环境变量传入，不能依赖固定网卡名。

### 2.4 Foxy 兼容修改与测试未同步

实测分支已包含部分正确方向的兼容修改，例如：

- 移除 `rclpy.SignalHandlerOptions.NO`；
- 将 `isinstance(value, A | B)` 改为 Python 3.8 可运行的元组形式；
- 调整部分 callback group 用法。

但现有定向测试仍有旧断言，且尚未在真实 Foxy/Python 3.8 环境完整运行。

## 3. 实施原则

1. 不直接把 `wip-changes` 整体合并到 `main`；按问题逐项重新实现或选择性移植。
2. Unitree 仓库中的官方 G1 示例是 Sport API 协议行为的首要依据。
3. 先验证只读状态和查询请求，再发送停止请求，最后才进行低速运动测试。
4. `official_loco` 基础闭环稳定前，不让语音、Agent 或 TextOp 自动触发真实运动。
5. ROS 基础环境、TextOp 推理环境和模型文件分别记录，避免把环境问题混为同一个问题。
6. 每一个实机阶段都必须有停止手段、现场监护和可回滚版本。

## 4. 分阶段执行计划

### 阶段 A：切换并记录 Foxy 环境（用户执行）

在机器人或与机器人一致的系统上完成 Foxy 环境切换，并记录以下信息：

```bash
lsb_release -a
python3 --version
python3.8 --version
source /opt/ros/foxy/setup.bash
echo "$ROS_DISTRO"
ros2 doctor --report
ros2 pkg prefix rclpy
ros2 pkg prefix unitree_api
ros2 interface show unitree_api/msg/Request
ros2 interface show unitree_api/msg/Response
ip -br link
ip -br addr
echo "$RMW_IMPLEMENTATION"
echo "$CYCLONEDDS_URI"
```

然后验证只读话题：

```bash
ros2 topic list
ros2 topic info /lowstate -v
ros2 topic echo /lowstate --once
ros2 topic info /api/sport/request -v
ros2 topic info /api/sport/response -v
```

完成标准：

- `ROS_DISTRO=foxy`；
- Python 为 3.8；
- `unitree_api/msg/Request` 和 `Response` 可见；
- 能稳定收到 `/lowstate`；
- 已确认机器人通信使用的网卡名、ROS domain 和 RMW 实现。

### 阶段 B：统一仓库 Foxy/Python 3.8 基线

环境信息确认后，在独立修复分支完成：

1. 统一 Makefile、Python 项目约束、锁文件和静态检查目标；
2. 检查依赖是否提供 Python 3.8 可用版本，必要时调整版本；
3. 修复 Python 3.8 不兼容的运行时类型表达式和标准库 API；
4. 修复 Foxy 与 Humble 之间的 `rclpy` API 差异；
5. 更新构建、启动和测试文档；
6. 明确 TextOp 是否共用 ROS Python 3.8 环境，或采用独立部署方式。

完成标准：

```bash
make bootstrap
make build
make test
```

以上命令在 Foxy 环境可重复执行，且不隐式加载 Humble。

### 阶段 C：修复 `g1_interface` Sport API 协议

1. 为 `SportApiClient` 注入可测试的请求 ID 生成器；
2. 默认 ID 生成器使用 `time.monotonic_ns()`；
3. 对极端情况下的重复值做单调递增保护；
4. 严格使用 `identity.id` 查找 pending request；
5. 校验响应 `api_id` 与 pending request 一致；
6. 移除按 `api_id` 弹出请求的兜底行为；
7. 增加错误 ID、错误 API ID、乱序响应、重复响应和超时测试。

完成标准：

- 单元测试明确验证请求 ID 为纳秒级单调值；
- 多个相同 API 请求可以正确区分；
- 未匹配响应不会清除其他 pending request；
- `get_fsm_mode` 和 `set_velocity` 的响应均能正确关联。

### 阶段 D：修复 DDS 与原生消息接入

1. 修复 CycloneDDS XML 引号和结构；
2. 将网卡、domain ID 和是否允许 multicast 参数化；
3. 按实机输出确认 `/lowstate`、`/api/sport/request`、`/api/sport/response` 的实际消息类型；
4. 统一文档中的消息类型，避免使用不存在或错误的 `SportRequest` 类型；
5. 检查 Foxy 下 publisher/subscription 的 QoS 是否与 Unitree 官方示例兼容。

完成标准：

- DDS XML 可被解析；
- 不修改代码即可选择实际网卡；
- 项目节点与 Unitree 原生节点能互相发现；
- 状态话题持续接收，Sport API 请求和响应均可观测。

### 阶段 E：无运动实机联调

启动 `g1_interface` 和安全节点，但禁止非零速度输出：

1. 验证 lowstate、IMU、模式和健康状态发布；
2. 仅发送 `get_fsm_mode` 等只读查询；
3. 检查请求 ID、响应 ID、API ID、状态码和延迟；
4. 验证超时、错误响应和节点退出流程；
5. 验证 DDS 断开后健康状态降级。

完成标准：

- 连续运行期间无错误匹配和 pending request 泄漏；
- 健康状态能区分正常、超时和通信中断；
- 节点退出时不会产生异常运动请求。

### 阶段 F：受控运动实机联调

现场清空机器人周围区域并准备物理停止手段，按以下顺序测试：

1. 零速度停止请求；
2. 极短持续时间、最低可观察速度的前进请求；
3. 指令截止时间自动停止；
4. lowstate 丢失自动停止；
5. safety heartbeat 丢失自动停止；
6. 连续相同 API 请求及响应关联；
7. 节点退出时只发送一次停止请求。

任何一步出现 ID 不匹配、模式不明、状态不新鲜或停止未确认，应立即终止后续运动测试。

### 阶段 G：恢复上层功能

仅在 `official_loco` 闭环稳定后，依次恢复：

1. `safety_control` 完整策略；
2. `voice_bridge` 文本/语音指令；
3. Pi Agent；
4. TextOp generator、tracker 和 low-level guard；
5. TextOp 模型下载、路径和哈希等部署特例。

每恢复一层，都重新验证停止链路和控制权归属。

## 5. 测试矩阵

| 层级 | 环境 | 必测内容 |
|---|---|---|
| 纯 Python 单元测试 | Python 3.8 | 配置、转换器、请求 ID、响应匹配、超时 |
| ROS 单元/集成测试 | ROS 2 Foxy | 消息导入、节点启动、publisher/subscription、shutdown |
| 桌面通信测试 | Foxy + Unitree overlay | DDS 发现、lowstate、Sport API 查询 |
| 实机无运动测试 | G1 | 状态、模式查询、健康检查、超时 |
| 实机受控运动测试 | G1 + 现场监护 | 低速指令、deadline、watchdog、停止 |
| 上层链路测试 | G1 | 语音、Agent、TextOp 与安全控制组合 |

## 6. 提交与分支策略

建议从更新后的 `main` 建立修复分支，按以下粒度提交：

1. `build: align workspace with ROS 2 Foxy and Python 3.8`
2. `fix: use monotonic nanosecond IDs for Unitree Sport API`
3. `fix: make CycloneDDS robot interface configurable`
4. `test: cover Foxy node lifecycle and Sport API response matching`
5. `docs: update Foxy real-robot validation procedure`

不在同一个提交中混合模型文件、机器人本地绝对路径和基础 ROS 通信修复。

## 7. 环境切换后的交接信息

环境切换完成后，请提供阶段 A 命令输出，以及以下实机信息：

- 机器人/控制机操作系统版本；
- 实际网卡名和 IP；
- `ROS_DOMAIN_ID`；
- Unitree ROS 2 仓库版本或提交；
- `/api/sport/request` 和 `/api/sport/response` 的消息类型；
- 一条真实请求及对应响应的 `identity.id`、`api_id` 和状态码；
- 当前可用的物理或软件停止方式。

获得这些信息后，可以直接从阶段 B、C 开始修复，减少再次到实机上试错的次数。
