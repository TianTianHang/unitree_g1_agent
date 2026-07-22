# Unitree G1 Agent

TextOp 文本动作 Backend 的重写设计见 [`docs/textop_backend.md`](docs/textop_backend.md)。

## 统一启动

两种全身运动控制后端都通过同一个入口启动。该入口会自动启动
`g1_interface`、`safety_control`、`voice_bridge` 以及所选 backend 的执行节点：

```bash
ros2 launch g1_bringup g1_system.launch.py motion_backend:=official_loco
ros2 launch g1_bringup g1_system.launch.py motion_backend:=textop
```

仿真闭环可额外传入 `start_sim:=true`。TextOp 模式会自动启动 Generator、Tracker 和
`low_level_guard`；无需再逐个启动节点。自建 ASR 需要时使用
`start_custom_asr:=true asr_source_mode:=custom`。

面向 Unitree G1 的 ROS 2 Foxy 控制栈。ASR 事件先由 `voice_bridge`
转换为强类型运动意图，再经过 `safety_control` 校验；只有
`ValidatedLocoCommand` 或 `ValidatedActionCommand` 能进入 `g1_interface`
并生成 Unitree Sport API 请求。

## 10 分钟开发环境

真实机器人核心环境是 Ubuntu 20.04、ROS 2 Foxy、系统 Python 3.8；TextOp 推理使用独立的 Python 3.10 环境。
核心 ROS 构建使用 Foxy overlay，TextOp GPU 推理使用独立的 `.venv-textop` 和模型制品。
不要把 Foxy 的 ROS 环境与 TextOp 推理环境混用。

先准备 Unitree 官方 ROS 2 消息 overlay。以下方式任选其一：

- Makefile 会把固定版本的 `unitree_sdk2` 和 `unitree_ros2` 源码下载到 `.unitree/`；
- 可通过 `UNITREE_ROS2_WS=/absolute/path/to/cyclonedds_ws` 覆盖 Unitree ROS2 workspace；
- 默认 workspace 为 `.unitree/unitree_ros2/cyclonedds_ws`。

随后执行：

```bash
make unitree-build
make foxy-build
make foxy-test-core
make foxy-test-integration
make frontend
make check-textop-core
```

`make foxy-build` 会加载 `/opt/ros/foxy` 和 Unitree Foxy overlay，并将构建产物写入 `build-foxy/`、`install-foxy/` 和 `log-foxy/`。TextOp 的大体积 GPU 依赖仍通过显式的 `make bootstrap-textop` 管理。

## 从全新 clone 启动

```bash
git clone https://github.com/TianTianHang/unitree_g1_agent.git
cd unitree_g1_agent

# 下载固定 revision，并从源码构建/安装 Unitree SDK2 与 ROS2 消息 overlay
make unitree-build

# 构建项目 Foxy overlay
make foxy-build

# 每个新终端按此顺序加载环境
source /opt/ros/foxy/setup.bash
source .unitree/unitree_ros2/cyclonedds_ws/install-foxy/setup.bash
source install-foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# 本地仿真启动
ros2 launch g1_bringup g1_system.launch.py \
  motion_backend:=official_loco start_sim:=true
```

SDK2 安装到 `.unitree/install/sdk2/`。在外部 CMake 工程中使用时，将该目录加入
`CMAKE_PREFIX_PATH`，并将 `.unitree/install/sdk2/lib` 加入 `LD_LIBRARY_PATH`。

如需自定义 Unitree workspace：

```bash
UNITREE_ROS2_WS=/opt/unitree_ros2/cyclonedds_ws make foxy-build
```

Unitree SDK2 和 ROS2 overlay 均由 Makefile 从固定源码版本构建。

## TextOp 治理与验收

TextOp 的轻量测试和自研适配层静态检查通过 `make check-textop-core` 执行，并进入普通 CI。
需要 Torch、ONNX Runtime GPU 和 CUDA 的完整运行时验收统一使用：

```bash
make check-textop
```

该命令只使用 `.venv-textop` 执行推理相关测试，不会改写 Foxy 的 `install-foxy`。模型制品、GPU smoke
和实机验收要求见 [`docs/textop_runtime_acceptance.md`](docs/textop_runtime_acceptance.md)；
功能冻结、第三方边界和解冻条件见 [`docs/project_governance.md`](docs/project_governance.md)。
流式 `(prompt, duration)` 替换语义见
[`docs/textop_streaming_commands.md`](docs/textop_streaming_commands.md)。部署时先 source 普通
`install-foxy/setup.bash`，再 source `install-textop/setup.bash`，确保 TextOp console script 使用
`.venv-textop` 解释器。

## 可选 ASR 运行时

默认测试不会下载 ASR 模型或初始化 CUDA。需要运行本地 ASR 时安装锁定的
可选依赖：

```bash
make bootstrap-asr
```

ASR 的 `source_mode` 支持：

- `builtin`：只转发机器人原生 `/audio_msg` ASR；
- `custom`：只接受 `asr_node`；
- `both`：同时允许两种来源，并保留 `source`/`sequence_id` 供观测与上层去重。

## 常用入口

```bash
# 启动模拟器
source /opt/ros/foxy/setup.bash
source .unitree/unitree_ros2/cyclonedds_ws/install-foxy/setup.bash
source install-foxy/setup.bash
ros2 launch g1_sim g1_sim.launch.py

# 启动接口、安全和语音节点时，使用各包 config/ 下的配置
ros2 launch g1_interface g1_interface.launch.py
ros2 launch safety_control safety_control.launch.py
ros2 launch voice_bridge voice_bridge.launch.py
```

当前 topic 类型、字段、单位和允许保留 JSON 的边界见
[`docs/data_contracts.md`](docs/data_contracts.md)。调试面板使用说明见
[`docs/voice_bridge_debug_panel.md`](docs/voice_bridge_debug_panel.md)。

## 低层策略接入边界

Text-to-motion、motion tracking 和端到端策略不得直接发布 `/lowcmd`。策略后端发布
29 路 `LowLevelCommandCandidate`，并持有由 motion manager 分配的短期 lease；
`low_level_guard` 是唯一生成 35 槽 `unitree_hg/LowCmd`、填充机器人模式和 CRC 的节点。

```bash
ros2 launch low_level_guard low_level_guard.launch.py
```

当前 guard 在 lease、candidate 或 lowstate 过期时停止发布。真机使用前仍需为目标固件验证
明确的 hold/damping 退出策略。详细说明见
[`docs/low_level_guard.md`](docs/low_level_guard.md)。
