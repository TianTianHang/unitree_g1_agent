# Unitree G1 Agent

面向 Unitree G1 的 ROS 2 Humble 控制栈。ASR 事件先由 `voice_bridge`
转换为强类型运动意图，再经过 `safety_control` 校验；只有
`ValidatedLocoCommand` 或 `ValidatedActionCommand` 能进入 `g1_interface`
并生成 Unitree Sport API 请求。

## 10 分钟开发环境

支持的开发环境是 Ubuntu 22.04、ROS 2 Humble、系统 Python 3.10、
uv 0.11.26，以及用于调试面板的 Node.js/npm。项目统一使用根目录下的
`.venv-ros`；不要使用旧的 Python 3.11 `.venv` 运行 ROS 节点或测试。

先准备 Unitree 官方 ROS 2 消息 overlay。以下方式任选其一：

- 仓库根目录已有 `result/setup.bash`；
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
