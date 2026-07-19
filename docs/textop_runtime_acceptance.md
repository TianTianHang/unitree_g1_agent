# TextOp Runtime Integration 验收目标

本文档把 TextOp runtime integration 阶段的目标转换为可执行的验收条目。验收默认使用
`motion_backend:=textop`，GPU 固定为 `cuda:3`；`official_loco` 只作为拓扑隔离的对照组。

## 验收分层

### A. 运行环境与模型制品

| ID | Given | When | Then | 类型 |
| --- | --- | --- | --- | --- |
| A-1 | 项目 ROS 推理环境已创建 | 启动 TextOp generator/tracker | 两个 console script 的解释器均为项目管理的 Python 3.10；不依赖系统 Python 或 `../TextOp/.venv` | 自动 + 部署 |
| A-2 | generator 执行 preflight | 设备参数不是 `cuda:3`、CUDA 不可用或 GPU 数量不足 4 张 | 在加载 checkpoint/VAE 前以非零状态退出，日志明确指出失败项；不切 CPU、其他 GPU 或 official loco | 自动 |
| A-3 | tracker 执行 preflight | ONNX Runtime 缺失或没有 `CUDAExecutionProvider` | 在创建推理 session 前失败；实机配置不得静默使用 CPU provider | 自动 |
| A-4 | 模型 manifest 已配置 | 启动并校验制品 | checkpoint、VAE、统计量、归一化文件和 ONNX 文件均存在且 SHA-256 匹配；RobotMDAR inference distribution 有固定版本/来源元数据 | 自动 + 部署 |
| A-5 | 运行时 import 路径已生效 | 扫描 `sys.path`、module origin 和启动脚本 | 不出现 `/home/ubuntu/Desktop/TextOp` checkout、editable install、`.pth` 注入或 launch 前临时 `PYTHONPATH` | 自动 |

### B. 启动拓扑与低层控制边界

| ID | Given | When | Then | 类型 |
| --- | --- | --- | --- | --- |
| B-1 | `motion_backend:=textop` | 启动统一 launch | 创建 `g1_interface(textop)`、generator、tracker、`low_level_guard`；不创建 official loco 的运动执行节点 | launch smoke |
| B-2 | `motion_backend:=official_loco` | 启动统一 launch | 不创建 TextOp generator/tracker/guard；保留官方 loco 拓扑 | launch smoke |
| B-3 | TextOp 拓扑运行 | 枚举 `/lowcmd` publishers | 只有 `low_level_guard` 能发布真实 `/lowcmd`；generator/tracker 不直接发低层命令 | graph inspection |
| B-4 | TextOp 拓扑运行 | 枚举 Sport API 请求 | 不向 `/api/sport/request` 发送官方 loco 运动请求；backend 选择只能在启动前通过参数决定 | graph + log |

### C. Generator 推理与输出 ABI

| ID | Given | When | Then | 类型 |
| --- | --- | --- | --- | --- |
| C-1 | 合法文本 goal、ready tracker、可用 lease | generator 完成一次推理 | 产生 `MotionReferenceSegment`；每个 primitive 的关节目标为 `[frames, 29]`，位置、速度、anchor pose 全部 finite | 单元/集成 |
| C-2 | GPU3 和固定模型制品 | 运行 primitive smoke | 输出 shape 为 `[8, 29]`（或 manifest 声明的固定帧数 × 29），device 为 `cuda:3`，不发生隐式 CPU 拷贝 | GPU smoke |
| C-3 | 连续 primitive history 已存在 | 生成下一个 primitive | history、absolute pose、segment index 和 `reset` 语义连续；不重复首帧、不跳过帧 | 单元 |
| C-4 | 输入文本为空、模型异常或输出含 NaN/Inf | 执行 goal | goal 失败且不发布 candidate/reference，不申请新的 lease | 单元/集成 |

### D. Tracker 与 pelvis odometry readiness

| ID | Given | When | Then | 类型 |
| --- | --- | --- | --- | --- |
| D-1 | 缺少 `/odom` 或 odometry 过期 | ExecuteMotion goal 到达 | 拒绝 goal；不申请 lease、不生成 candidate，并发布 `ready=false` 及具体原因 | 单元/集成 |
| D-2 | odometry frame、child frame、timestamp、四元数或数值非法 | 收到 odometry | 丢弃该消息，readiness 保持 false，日志包含失败字段 | 单元 |
| D-3 | 合法 pelvis odometry | tracker 构建 observation | twist 按消息声明的 body/child frame 转换为 world-frame，再按模型需要转换；使用 odometry orientation，不读取不匹配的 IMU 姿态 | 单元 |
| D-4 | lowstate 少于 29 路、数值非法或过期 | tracker tick | readiness 为 false，candidate 不发布 | 单元 |
| D-5 | readiness status 长时间未更新 | 新 ExecuteMotion goal 到达 | generator 将 status 视为 stale 并拒绝 goal，不沿用旧 ready 状态 | 集成 |

### E. Stop/cancel 与 lease 事务

| ID | Given | When | Then | 类型 |
| --- | --- | --- | --- | --- |
| E-1 | ExecuteMotion 正在生成或执行 | Action cancel 或允许的 `/g1/safe_cmd/stop` 到达 | 两条路径调用同一个 request-scoped stop 事务；立即使 lease inactive，终态只写一次 | 单元/集成 |
| E-2 | GPU future 在 stop 后返回 | future 完成 | 通过 stop generation 检查丢弃迟到结果；不发布 reference/candidate | 并发单元 |
| E-3 | tracker 已收到 inactive lease | 后续 tick | 清空 reference buffer、frame index 和 previous action，不再发布 candidate | 单元 |
| E-4 | guard 观察到 lease inactive/expired | 下一控制周期 | 停止发布 `/lowcmd`；不得因迟到消息恢复发布 | 集成/实机 |
| E-5 | 当前没有活动请求或重复 stop | stop 消息到达 | 幂等 no-op；不创建 lease、不触发 Sport API 请求、不改变 backend | 单元 |

### F. Fail-closed 与故障隔离

| ID | Given | When | Then | 类型 |
| --- | --- | --- | --- | --- |
| F-1 | 任一依赖、制品、ABI、readiness 检查失败 | 启动或 goal admission | 失败发生在大模型加载/lease 申请前，并给出可诊断错误 | 自动 |
| F-2 | 推理超时、ONNX session 异常或节点崩溃 | runtime 发生故障 | 不自动切换 backend、不自动进入 official loco、不绕过 guard；由启动编排/人工重新选择配置 | 故障注入 |
| F-3 | TextOp 节点停止 | guard/lease 超时 | `/lowcmd` 发布停止，系统保持 fail-closed | 集成/实机 |

## 通过标准

1. A、B、D、E、F 类的自动测试全部通过。
2. C 类单元测试全部通过；C-2 和 E-4 至少完成一次 GPU/实机 smoke（若硬件不可用，必须记录为未执行，不得标记通过）。
3. `official_loco` 与 `textop` 两种启动图均满足 B 类隔离要求。
4. 任何失败都不能通过降级到 CPU、其他 GPU、旧 checkout 或官方控制路径来“通过”。
5. 验收报告记录：代码提交、Python/torch/onnxruntime/RobotMDAR 版本、GPU 型号与编号、模型 manifest 及 SHA-256、测试命令和结果。

## 测试矩阵

| 层级 | 目标 | 载体 |
| --- | --- | --- |
| 单元 | preflight、manifest、ABI、readiness、stop gate、reference buffer | `src/textop_backend/tests` |
| 集成 | generator→tracker→guard、lease 生命周期、safe stop | ROS launch + fake messages |
| GPU smoke | RobotMDAR primitive 在 GPU3 上运行 | 项目 Python 3.10 环境 |
| Tracker smoke | ONNX `[1,431] -> [1,29]` 与 CUDA provider | ONNX Runtime GPU |
| 拓扑 | backend 静态选择与 publisher/consumer 集合 | `ros2 launch`、graph inspection |
| 实机 | `/odom` 来源、真实 lowstate、低层停止行为 | G1 hardware（需单独批准） |

