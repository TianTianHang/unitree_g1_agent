# TextOp Motion Backend 设计

TextOp 与官方 Loco 的选择采用启动期静态配置，运行期间禁止切换；启动拓扑、控制权互斥
和 stop 路由见 [`motion_backend_selection.md`](motion_backend_selection.md)。本文只定义
TextOp 后端内部推理与控制契约。

本文定义本仓库内 TextOp 推理与控制实现的架构真相。实现不得启动、导入或通过
`PYTHONPATH` 引用相邻 `../TextOp` 工作树中的部署脚本。模型权重和统计数据是受
manifest 管理的外部资产；推理网络、diffusion 和 motion feature 重建代码直接维护在
本仓库 `textop_backend.textop_model` 中，不安装独立的 RobotMDAR package/wheel。

## 责任边界

```text
ExecuteMotion(prompt, request_id)
              │
              ▼
       TextOpMotionBackend
       ├── textop_generator_node：prompt → reference segments
       ├── ReferenceBuffer：连续、有界、按 request 隔离
       └── textop_tracker_node：reference + LowState → 29 路阻抗目标
              │
              ▼
 LowLevelCommandCandidate(q,dq,tau,kp,kd)
              │
              ▼
       low_level_guard → /lowcmd
```

TextOp 在平台层是一个完整 MotionBackend，但运行时拆为生成与跟踪两个进程，避免
GPU diffusion 阻塞 50 Hz 跟踪循环。只有 `low_level_guard` 可以发布真实 `/lowcmd`。

## RobotMDAR 推理契约

checkpoint 配置固定为：57 维 normalized motion feature、2 帧 history、8 帧 future、
5 个 diffusion timestep、50 Hz、full sampling。一次生成按以下顺序执行：

```text
prompt → CLIP ViT-B/32 → diffusion denoiser → VAE decode
       → denormalize → reconstruct_motion → 23 DoF 扩展为 29 DoF
```

连续生成必须跨 primitive 保存最后 2 帧 normalized feature 和 `abs_pose`。异步结果必须
携带 request ID；已取消或已被新请求替换的结果不得进入 reference buffer。

本仓库重写 ROS 编排、状态机、模型构造、diffusion 采样、重建与数据转换，不复用
TextOpDeploy 的 `rmdar.py`，运行时也不导入外部 `robotmdar`。内置源码只保留当前
checkpoint 推理所需网络定义与算子，不纳入训练器和 IsaacLab 训练环境。

## MotionReferenceSegment

Backend 内部使用强类型 segment，不使用 `Float32MultiArray` 或 toggle：

| 字段 | 契约 |
| --- | --- |
| `request_id` | 非空；与当前执行请求完全一致 |
| `segment_index` | 从 0 开始严格递增 |
| `start_frame` | 从 0 开始连续，不得重叠或留洞 |
| `dt` | TextOp v1 固定为 0.02 秒 |
| `reset` | 仅首段为 true；原子清除旧请求数据 |
| `end_of_motion` | 标记该请求不会再产生后续帧 |
| `joint_position` | 每帧 29 维，IsaacLab joint order，rad |
| `joint_velocity` | 每帧 29 维，IsaacLab joint order，rad/s |
| `anchor_position` | 每帧 3 维 world frame，m |
| `anchor_orientation_wxyz` | 每帧归一化四元数，world frame |

消费者必须拒绝 NaN/Inf、shape 错误、非连续 segment、request 混用和非法四元数。
新请求 reset 时必须同时清空旧尾部、tracker frame 与 last action。

## Tracker 契约

Tracker 每 20 ms 执行一次。ONNX 输入 `obs` 为 `[1,431]`，输出 `actions` 为 `[1,29]`。
431 维按以下顺序拼接，顺序属于模型 ABI：

| slice | 内容 | 维度 |
| --- | --- | ---: |
| 0:145 | future joint position，5×29 | 145 |
| 145:290 | future joint velocity，5×29 | 145 |
| 290:305 | future anchor position in robot anchor frame，5×3 | 15 |
| 305:335 | future anchor orientation 6D，5×6 | 30 |
| 335:338 | projected gravity | 3 |
| 338:341 | base linear velocity in body frame | 3 |
| 341:344 | base angular velocity in body frame | 3 |
| 344:373 | joint position relative to default | 29 |
| 373:402 | joint velocity | 29 |
| 402:431 | previous raw action | 29 |

前视索引为当前帧 `t..t+4`，越过已知动作末尾时重复最后一帧。不得保留旧部署代码中
强制将 anchor position 清零的逻辑。orientation 6D 必须与训练时
`matrix_from_quat(relative_quat)[..., :2].reshape(...)` 一致。

ONNX raw action 使用 IsaacLab order，且没有 tanh：

```text
target_q = default_q + raw_action * action_scale
dq = 0
tau = 0
kp, kd = model manifest
```

输出前显式重排为 Unitree G1 motor index 0..28，并发布
`LowLevelCommandCandidate`。边界检查与最终 CRC 由 `low_level_guard` 再次执行。

## Model manifest

每组 generator/tracker 资产必须有一个版本化 YAML manifest，绑定：

- model ID、robot/control profile 和 50 Hz 控制频率；
- ONNX 路径、SHA-256、输入输出名称及 shape；
- IsaacLab 与 Unitree 两套 29 关节名称；
- Unitree order 的 `default_q`、`action_scale`、`kp`、`kd`；
- RobotMDAR checkpoint、VAE、normalization、CLIP ViT-B/32 和各自 SHA-256；
- `future_steps=5`、与训练配置一致的 `anchor_body`、`quaternion_order=wxyz`。

当前 `latest.onnx` 对应训练配置中的 `anchor_body_name` 是 `pelvis`，所以实机状态必须使用
pelvis/base 的位置和姿态构造相对 anchor observation；不能把 torso 位姿或人为清零的位置
混入该策略。后续模型必须在各自 manifest 中声明自己的 anchor body。

## 当前预训练资产

仓库提供 `config/textop_pretrained.yaml`，将当前确认的五个资产绑定为一个不可混用的模型组：

- RobotMDAR `ckpt_200000.pth`；
- RobotMDAR `vae.pth`；
- RobotMDAR 实际用于 57 维归一化的 `meanstd.pkl`；
- OpenAI CLIP `ViT-B-32.pt`；
- Tracker `latest.onnx`，ABI 为 `obs[1,431] → actions[1,29]`。

Generator 和 Tracker 启动时读取同一个 manifest，并在加载模型前逐个验证 SHA-256。
组合 launch 默认使用该 manifest。部署到其他机器时必须同步复制制品并更新 manifest
路径与 SHA-256。

启动时必须先验证 manifest、文件 hash、shape、关节双射和所有数值。验证失败时不得申请
low-level lease。

## 生命周期与取消

Generator 状态为 `UNLOADED → LOADING → READY → GENERATING → DRAINING → READY`，
任意状态均可进入 `FAULT`。Tracker 只有收到首段、fresh LowState 且 lease 生效后才能发布。

Cancel 或 fault 必须作为一个逻辑事务完成：使在途生成结果失效、清空 buffer、重置
frame/last action、停止 candidate、撤销 lease。动作自然结束只允许配置的短暂 hold，随后
执行同样的停止流程，不无限锁定最后一帧。

Generator 以 `ceil(duration / (8 * 0.02))` 计算完整 primitive 数，不截断最后一个
primitive。首段发布后才申请 lease，并在 Action 生命周期内续租。Tracker 每次成功执行
策略后发布强类型 `TextOpTrackerStatus`；Generator 只以匹配 request ID 的真实消费帧数
填充 Action feedback，并在最后一帧执行后撤销 lease。Tracker 状态超时同样触发 fail-safe
停止，不能用墙钟伪造执行完成。

## 测试策略

实现采用先红后绿：先用纯 Python 单元测试固定 manifest、关节映射、buffer、431 维 ABI、
action decode 和状态机；再实现 ROS adapter 测试；最后用假的 RobotMDAR runtime 与假的
ONNX session 做集成测试。GPU checkpoint smoke test 单独标记，不作为普通 CI 的硬依赖。
