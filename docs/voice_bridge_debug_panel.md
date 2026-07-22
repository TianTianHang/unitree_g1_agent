# Voice Bridge Debug Panel 启动指南

本文说明如何启动 `voice_bridge_debug` Web 调试面板，用于本地模拟 ASR、观察 `voice_bridge` 调试事件、查看机器人状态和决策时间线。

## 前置条件

- 已安装 ROS 2 Foxy，并能 `source /opt/ros/foxy/setup.bash`。
- 已在仓库根目录完成依赖安装和构建。
- 如需重新构建前端，需要本机可用 `node`/`npm`。

调试面板默认只监听 `127.0.0.1:8765`。如果要绑定非 loopback 地址，必须在配置里设置 `server.allow_remote: true`；这会允许远程页面发布模拟 ASR，可能触发机器人命令链，使用前要确认网络环境安全。

## 生产模式启动

在仓库根目录执行：

```bash
make foxy-build
source install-foxy/setup.bash
ros2 run voice_bridge_debug debug_panel_server -- --prod
```

启动成功后打开：

```text
http://127.0.0.1:8765
```

`--prod` 会从 Python 包内的 `voice_bridge_debug/frontend_dist` 提供前端静态文件。

## 同时启动 voice_bridge

调试面板只负责发布模拟 ASR 和观察 topic；要看到完整 agent 输出、决策和命令链，还需要另开一个终端启动 `voice_bridge`：

```bash
source /opt/ros/foxy/setup.bash
source .unitree/unitree_ros2/cyclonedds_ws/install-foxy/setup.bash
source install-foxy/setup.bash
ros2 launch voice_bridge voice_bridge.launch.py \
  config_path:=src/voice_bridge/config/voice_bridge.yaml
```

`voice_bridge` 会发布 `/voice/debug/events`，调试面板订阅该 topic 并显示 agent 结果、会话决策和命令发布事件。

## 前端开发模式

开发 UI 时建议后端和 Vite 分开运行。

终端 1：启动后端 API 和 WebSocket，不带 `--prod`：

```bash
source /opt/ros/foxy/setup.bash
source .unitree/unitree_ros2/cyclonedds_ws/install-foxy/setup.bash
source install-foxy/setup.bash
ros2 run voice_bridge_debug debug_panel_server
```

终端 2：启动 Vite：

```bash
cd src/voice_bridge_debug/frontend
npm ci
npm run dev
```

然后打开 Vite 输出的地址，通常是：

```text
http://127.0.0.1:5173
```

Vite 已配置代理：

- `/api` -> `http://127.0.0.1:8765`
- `/ws` -> `ws://127.0.0.1:8765`

## 重新打包前端

修改前端后，如果要更新生产模式静态资源：

```bash
make frontend
make foxy-build
```

Vite 已直接把产物写入 Python 包的 `frontend_dist`。`make frontend` 会用
`npm ci` 重建，并检查已提交产物是否与源码一致；有意修改 UI 时先审查并
暂存生成文件，再重新运行该命令。

## 使用面板

1. 在 ASR 输入面板填写文本，例如 `小宇向前`。
2. 保持 `confidence` 在 `0.0` 到 `1.0` 之间。
3. 点击 `发送 ASR`。
4. 面板会把强类型 `g1_agent_msgs/msg/VoiceEvent` 发布到 `/g1/audio/asr`。
5. 如果 `voice_bridge` 正在运行，时间线会显示 `/voice/debug/events`、命令发布、安全决策和状态更新。

调试面板不会直接发布运动命令；它只向 `/g1/audio/asr` 发布模拟 ASR。后续是否产生 `/voice/cmd/*` 或 `/g1/safe_cmd/*`，由 `voice_bridge`、agent 和 safety 节点决定。

## 自定义配置

默认配置位于：

```text
src/voice_bridge_debug/config/debug_panel.yaml
```

使用自定义配置启动：

```bash
source /opt/ros/foxy/setup.bash
source .unitree/unitree_ros2/cyclonedds_ws/install-foxy/setup.bash
source install-foxy/setup.bash
ros2 run voice_bridge_debug debug_panel_server -- \
  --config /path/to/debug_panel.yaml \
  --prod
```

常用配置项：

- `server.host`: 默认 `127.0.0.1`
- `server.port`: 默认 `8765`
- `server.allow_remote`: 非 loopback host 必须显式设为 `true`
- `topics.asr`: 面板模拟 ASR 发布 topic，默认 `/g1/audio/asr`
- `topics.voice_debug_events`: `voice_bridge` 调试事件 topic，默认 `/voice/debug/events`
- `timeline.max_events`: 内存时间线保留事件数，默认 `200`

## 快速排查

- 页面打不开：确认 `ros2 run voice_bridge_debug debug_panel_server -- --prod` 仍在运行，并检查端口是否是 `8765`。
- 页面有但无事件：确认 `voice_bridge` 已启动，并检查 `/voice/debug/events` 是否有消息。
- ASR 没有效果：确认 `/g1/audio/asr` topic 与 `voice_bridge` 配置一致。
- `--prod` 报 `frontend static directory not found`：在仓库根目录执行 `make frontend` 和 `make foxy-build`。
- 绑定 `0.0.0.0` 失败：配置里必须设置 `server.allow_remote: true`。
