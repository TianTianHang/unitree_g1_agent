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

面向 Unitree G1 的 ROS 2 Humble 控制栈。ASR 事件先由 `voice_bridge`
转换为强类型运动意图，再经过 `safety_control` 校验；只有
`ValidatedLocoCommand` 或 `ValidatedActionCommand` 能进入 `g1_interface`
并生成 Unitree Sport API 请求。

## 10 分钟开发环境

支持的开发环境是 Ubuntu 22.04、ROS 2 Humble、系统 Python 3.10、
uv 0.11.26，以及用于调试面板的 Node.js/npm。常规 ROS 开发统一使用根目录下的
`.venv-ros`；TextOp GPU 推理使用独立的 `.venv-textop`。不要使用旧的 Python 3.11
`.venv` 运行 ROS 节点或测试，也不要在两个正式环境之间手工安装依赖。

先准备 Unitree 官方 ROS 2 消息 overlay。以下方式任选其一：

- `result` 指向包含 ROS overlay 的 Nix 构建结果；
- 已构建官方 `unitree_ros2/cyclonedds_ws`，并通过
  `UNITREE_ROS2_WS=/absolute/path/to/cyclonedds_ws` 指定；
- 官方 workspace 位于主 checkout 的
  `.unitree/unitree_ros2/cyclonedds_ws`，Makefile 会自动发现。

随后执行：

```bash
make bootstrap
make build
make test
make test-integration
make frontend
make lint
make check-textop-core
```

`make bootstrap` 会验证 `/usr/bin/python3` 为 Python 3.10、uv 为
0.11.26，并按 `uv.lock` 创建或同步 `.venv-ros`。它启用 ROS Humble
所需的系统 site-packages，同时禁用用户全局 site-packages 和 pytest
插件自动加载。

如需自定义 Unitree workspace：

```bash
UNITREE_ROS2_WS=/opt/unitree_ros2/cyclonedds_ws make build
```

Nix 仅是可选的 Unitree SDK/ROS overlay 获取方式，不参与 Python 环境
管理；本地开发和验证不要求 Nix 可用。

## TextOp 治理与验收

TextOp 的轻量测试和自研适配层静态检查通过 `make check-textop-core` 执行，并进入普通 CI。
需要 Torch、ONNX Runtime GPU 和 CUDA 的完整运行时验收统一使用：

```bash
make check-textop
```

该命令只使用 `.venv-textop` 执行推理相关测试，不会改写 `.venv-ros`。模型制品、GPU smoke
和实机验收要求见 [`docs/textop_runtime_acceptance.md`](docs/textop_runtime_acceptance.md)；
功能冻结、第三方边界和解冻条件见 [`docs/project_governance.md`](docs/project_governance.md)。
流式 `(prompt, duration)` 替换语义见
[`docs/textop_streaming_commands.md`](docs/textop_streaming_commands.md)。部署时先 source 普通
`install/setup.bash`，再 source `install-textop/setup.bash`，确保 TextOp console script 使用
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
source /opt/ros/humble/setup.bash
source install/setup.bash
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
