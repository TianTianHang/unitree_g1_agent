# TextOp 可部署运行阶段设计

## 阶段目标

上一阶段已经完成 TextOp 推理、Tracker、低层保护和启动期静态 backend 选择。本阶段使
`motion_backend:=textop` 从“拓扑能够构造”变成“在项目自己的运行环境中能够启动、准入、
停止并保持 fail-closed”。

本阶段交付四项能力：

1. TextOp ROS 节点使用项目管理的 Python 3.10 推理环境启动，不借用 `../TextOp/.venv`；
2. RobotMDAR、Torch、CLIP 和 ONNX Runtime 依赖可复现安装，并在启动时自检；
3. `/g1/safe_cmd/stop` 能可靠终止当前 `ExecuteMotion`、撤销 lease；
4. Tracker 对 pelvis odometry 的来源、坐标系和 freshness 进行显式准入。

本阶段仍不实现运行时 backend 切换、自动切回 official loco、机器人原生控制模式切换，
也不在来源不明确时伪造 `/odom`。

## 已确认的问题

当前统一 launch 在 `textop` 模式下会正确构造：

```text
g1_interface(textop mode)
textop_generator_node
textop_tracker_node
low_level_guard_node
```

但实际启动暴露出两个部署问题：

- ROS console script 的 shebang 指向系统 Python，找不到 `torch`、`onnxruntime` 等推理依赖；
- `../TextOp/.venv` 中的 `robotmdar` 来自外部源码目录的 editable/path 注入，不是项目可复现依赖。

此外，TextOp 模式已经禁止 `g1_interface` 消费 Sport stop，但还没有新的消费者将
`/g1/safe_cmd/stop` 映射为 TextOp 取消。

## 最终进程与数据流

```text
                         启动前静态配置
                  motion_backend := textop
                              |
                              v
               g1_bringup / 启动准入与日志
                              |
          +-------------------+--------------------+
          |                   |                    |
          v                   v                    v
 g1_interface(state only)  TextOp Generator    TextOp Tracker
          |                   |                    ^
      /lowstate        ExecuteMotion Action        |
          |                   |              /lowstate + /odom
          |                   v                    |
          |             RobotMDAR runtime          |
          |                   |                    |
          |          MotionReferenceSegment -------+
          |                                        |
          |                                  431-dim obs
          |                                        |
          |                                  ONNX action[29]
          |                                        |
          |                           LowLevelCommandCandidate
          |                                        |
          +-------------------+--------------------+
                              v
                       low_level_guard
                              |
                           /lowcmd

 /g1/safe_cmd/stop
          |
          v
 TextOp Generator stop gate
          |
          +--> generation token invalid
          +--> late GPU result discarded
          +--> lease inactive
          +--> Action canceled/aborted with reason
          +--> Tracker loses active lease
          +--> low_level_guard stops /lowcmd
```

## 推理运行环境

### 单一项目环境

项目继续使用 `.venv-ros`，其解释器固定为 `/usr/bin/python3` 对应的 Python 3.10，并启用
ROS Humble 所需的 system site-packages。TextOp 依赖作为独立 uv dependency group 管理：

```text
dependency-groups.textop
  torch + CUDA runtime
  onnxruntime-gpu
  openai-clip
  hydra-core
  omegaconf
  scipy / transforms3d 等模型运行依赖
  robotmdar inference distribution
```

普通开发和非 TextOp CI 不强制安装大体积 GPU 依赖；部署或 GPU smoke test 使用显式命令：

```bash
make bootstrap-textop
make build-textop
```

`build-textop` 必须让 `colcon` 自身运行在 `.venv-ros` 解释器中，使安装后的
`textop_generator_node` 和 `textop_tracker_node` console script shebang 指向同一环境。
只在 shell 中临时修改 `PYTHONPATH` 不算有效部署方案。

### RobotMDAR 依赖边界

本仓库拥有推理编排、状态机、连续 primitive、重建调用和 ROS adapter。模型网络定义作为
固定版本的 inference distribution 安装，但不得：

- 从 `/home/ubuntu/Desktop/TextOp` 或其他 checkout 直接 import；
- 使用 editable install、`.pth` 路径注入或 launch 前临时 `PYTHONPATH`；
- 启动外部 TextOp deploy/train 脚本；
- 在运行时从网络下载代码或模型。

RobotMDAR inference distribution 必须有确定版本、来源提交和 SHA-256。构建产物可以来自经
审查源码生成的 wheel，但 wheel/lock 信息必须归项目管理。若现有 RobotMDAR 包无法隔离
训练依赖，应提取只包含当前 checkpoint 所需网络定义和数据重建逻辑的 inference package，
而不是把整个外部仓库加入运行路径。

### 启动环境自检

TextOp 节点加载大型权重前执行快速 preflight：

```text
Python == 3.10
torch importable
torch.cuda.is_available()
requested device == cuda:3
CUDA device count > 3
onnxruntime has CUDAExecutionProvider
robotmdar distribution version/digest matches lock
manifest assets and hashes valid
ONNX ABI == [1,431] -> [1,29]
```

任一检查失败时节点以非零状态退出，并输出具体检查项。不得静默切换到 CPU、其他 GPU 或
official loco。Tracker ONNX 可显式配置 provider，但 TextOp 实机配置必须要求 CUDA provider；
测试配置可以使用 CPU provider。

## Stop/Cancel 设计

### 唯一停止事务

Generator 是当前请求、生成 token 和 lease 的唯一所有者，因此 TextOp stop gate 放在
`textop_generator_node` 内，而不是让另一个节点直接伪造 lease 或清空 Tracker。

Generator 新增 `/g1/safe_cmd/stop` 的 `ValidatedActionCommand` subscription。只有满足以下
条件的消息触发停止：

- safety decision 为 allow；
- command kind 为 action；
- action 为 `stop` 或 `cancel`；
- 消息结构有效。

Stop 不受 lowstate、odometry、Tracker status 或模型状态 freshness 阻挡。没有活动请求时
stop 是幂等 no-op，并记录诊断，不创建 lease 或 Sport 请求。

### 并发与状态

ROS callback 不直接等待 GPU future。它只在锁内设置当前 request 的 stop generation，并
立即撤销 active lease：

```text
stop callback
  acquire lock
  capture active_request_id
  increment stop_generation
  mark lease inactive and publish inactive lease once
  release lock

execute loop / future polling
  observes stop_generation mismatch
  engine.cancel(request_id)
  session.cancel(request_id)
  discards late result
  completes Action as canceled
```

Action protocol cancel 和 safe stop 使用同一个内部 `_request_stop(request_id, reason)`，避免
两套清理顺序。重复 stop、Action cancel 与异常同时发生时，inactive lease 最多发布一次，
请求终态只设置一次。

### Tracker 和 Guard 停止保证

Tracker 不需要订阅 stop topic。它只接受 active、匹配 request/profile 且新鲜的 lease；收到
inactive lease 后立即清空 reference buffer、frame index 和 previous action，不再发布 candidate。
即使 Tracker 尚未处理 inactive lease，`low_level_guard` 也必须在 lease inactive/expired 后停止
发布 `/lowcmd`。

“停止”在此处表示停止产生新的控制帧，不承诺机器人机械瞬时静止。机器人失去低层命令后的
物理行为由启动前选定的原生低层控制模式和 Unitree 控制器定义。

## Pelvis Odometry 准入

当前 Tracker 已消费 `nav_msgs/Odometry`，模型 manifest 要求 `anchor_body=pelvis`。本阶段不从
IMU 积分或 joint state 猜测全局位置，也不把 position 强制清零。

合法 odometry 必须满足：

| 项目 | 要求 |
| --- | --- |
| body | pelvis/base，与 manifest `anchor_body` 一致 |
| pose frame | 稳定 world/odom frame |
| twist | 明确表达 frame，并能转换到 body frame |
| orientation | 归一化、有限四元数 |
| position/velocity | 全部有限 |
| timestamp | 使用消息 header stamp，不只使用 callback 到达时间 |
| freshness | 默认小于 100 ms，参数可收紧 |
| continuity | 时间单调；拒绝明显倒退和超范围跳变 |

部署配置必须显式声明 odometry topic、world frame、child frame 和来源节点。来源尚未确定时，
TextOp backend 可以启动用于诊断，但不得接受 `ExecuteMotion` 或申请 lease。

Generator 接受 goal 前需要获得 Tracker readiness。readiness 至少包含：

```text
lowstate_fresh
odometry_fresh
anchor_body_matches
policy_loaded
guard_profile_matches
```

当前 `TextOpTrackerStatus` 只表达执行反馈，后续实现应扩展或新增独立 readiness/diagnostic，
不能用“最近收到过 Tracker status”代替启动准入。

## 启动与故障语义

TextOp launch 分为三个阶段：

```text
environment preflight
        -> model/manifest load
        -> ROS readiness and goal admission
```

- environment preflight 失败：进程退出，guard 无 lease；
- Generator 加载失败：不启动动作，不能降级到 CPU；
- Tracker 加载失败：Generator 拒绝 goal；
- odometry/lowstate 未就绪：节点保持存活并报告 not ready，但拒绝 goal；
- 运行中状态过期：撤销 lease并终止当前 Action；
- backend 节点退出：可以由部署监管器重启同一 TextOp backend，不切换 backend。

`g1_bringup` 继续只接收静态 `motion_backend`。TextOp 环境路径、GPU 和资产可以是启动参数，
但启动后不可改变控制链路，也不新增 backend switch service/topic。

## 测试计划

实现继续采用先红后绿。

### 纯逻辑测试

- runtime preflight 对 Python、CUDA device、provider 和依赖版本的判定；
- stop generation 对迟到 future 的失效；
- Action cancel、safe stop、异常和自然结束共享同一清理事务；
- 重复 stop 的幂等性；
- odometry stamp、frame、四元数、finite 和 freshness 校验。

### ROS adapter 测试

- TextOp 模式只有 Generator 消费 `/g1/safe_cmd/stop`；
- stop 后发布 inactive lease，随后不再有匹配 candidate；
- 无活动 goal 的 stop 不产生输出；
- 未 ready 时 `ExecuteMotion` goal 被拒绝；
- official loco 模式不启动 TextOp stop consumer。

### 启动测试

- console script 的解释器属于项目 `.venv-ros`；
- `motion_backend:=textop` 能同时 import Torch、RobotMDAR 和 ONNX Runtime；
- GPU 固定为 3，CUDA provider 生效；
- graph 中无 `/api/sport/request` publisher；
- `/lowcmd` 只有 `low_level_guard` publisher；
- 非法 backend 和缺失依赖均明确失败。

### 实机前 smoke test

1. GPU 3 完成一个 8 帧 primitive，输出 finite `[8,29]`；
2. ONNX 完成 `[1,431] -> [1,29]`；
3. 假 lowstate/odom 下完成 reference、candidate、lease 生命周期；
4. 在生成中、执行中分别发送 stop，确认 lease 立即 inactive；
5. 不连接机器人时确认没有任何其他 `/lowcmd` publisher。

## 实现顺序

1. 固定 TextOp dependency group、RobotMDAR inference 制品和项目解释器启动方式；
2. 增加可独立测试的 runtime preflight，并让 launch 失败信息可诊断；
3. 为 Generator 增加统一 stop transaction 和 safe stop subscription；
4. 增加 odometry 合约校验与 Tracker readiness；
5. 将 readiness 接入 Generator goal admission；
6. 增加 launch/graph/GPU smoke test，并更新部署说明。

每一步独立提交。任何一步都不能通过引入 backend 自动切换或绕过 `low_level_guard` 来转绿。
