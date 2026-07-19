# Motion Backend 启动期静态选择设计

## 目标

系统支持两类全身运动控制后端：

- `official_loco`：Unitree 官方 Sport/Loco API；
- `textop`：文本生成动作参考，并由配套 Tracker 输出 29 路低层关节指令。

后端只能在进程启动前通过配置选择。系统运行期间不提供 backend 切换 topic、service、
action 或自动降级逻辑。选择结果在本次进程生命周期内不可变。

本文是 motion backend 选择、控制权和启动拓扑的架构契约。各模型内部的数据 ABI 由
[`textop_backend.md`](textop_backend.md) 等后端文档定义。

## 核心原则

### 静态选择

统一启动配置必须包含：

```yaml
motion:
  backend: textop  # official_loco | textop
```

启动器读取该值并只构造对应后端的控制链路。节点启动后不得重新读取或修改 backend。
未知值、空值或同时声明多个 backend 必须导致启动失败，不能回退到默认后端。

### 控制链路互斥

任意时刻只允许一类执行器拥有全身运动控制权：

```text
official_loco  -> /api/sport/request
textop         -> low_level_guard -> /lowcmd
```

选择 `official_loco` 时，不启动 TextOp Generator、Tracker 和 `low_level_guard`。选择
`textop` 时，禁止将普通移动命令转发到 `/api/sport/request`，且只有
`low_level_guard` 可以发布 `/lowcmd`。

互斥必须由启动拓扑和节点配置共同保证，不能只依赖操作者不发送命令。

### 不负责运行时模式切换

本系统不在收到动作请求时调用 motion switcher、`switch_to_user_ctrl`、
`switch_to_internal_ctrl` 或等价接口。机器人原生控制模式必须在启动前由部署流程设置。

启动后发现机器人模式与所选 backend 不兼容时，系统必须保持无运动输出并报告错误，
不得自行切换到另一 backend。

## 启动矩阵

| 组件 | `official_loco` | `textop` |
| --- | --- | --- |
| 状态、音频与设备接口 | 启动 | 启动 |
| `/g1/safe_cmd/loco` 消费 | 启用 | 禁用 |
| `/api/sport/request` 运动命令 | 启用 | 禁用 |
| TextOp Generator | 不启动 | 启动 |
| TextOp Tracker | 不启动 | 启动 |
| `low_level_guard` | 不启动 | 启动 |
| `/lowcmd` publisher | 无 | 仅 `low_level_guard` |
| `/odom` 数据源 | 非必需 | 必需 |
| GPU | 非必需 | Generator 默认 `cuda:3` |

状态采集、健康检查、音频和机器人基础接口不等于运动控制，可以在两种拓扑中复用；但
`g1_interface` 的 Sport/Loco command bridge 必须受静态 backend 配置门控。

## `official_loco` 数据流

```text
 ASR / Agent / API
        |
        v
   LocoIntent
 /voice/cmd/loco
        |
        v
 safety_control
        |
        v
 ValidatedLocoCommand
 /g1/safe_cmd/loco
        |
        v
 g1_interface
        |
        v
 /api/sport/request
        |
        v
 Unitree Sport/Loco Controller
        |
        v
   机器人内部关节控制
```

该拓扑不得启动 `low_level_guard`，项目内不得存在 `/lowcmd` publisher。

## `textop` 数据流

```text
 Text motion request
 prompt + duration + request_id
        |
        v
 /g1/textop/execute_motion
 ExecuteMotion Action
        |
        v
 textop_generator_node
        |
        +--> CLIP -> RobotMDAR diffusion -> VAE -> reconstruct
        |                                      |
        |                                      v
        |                          8-frame MotionReferenceSegment
        |                                      |
        +--------------------> /g1/textop/reference
        |
        +--------------------> /g1/low_level/lease
                                               |
                         +---------------------+------------------+
                         |                                        |
                         v                                        v
                textop_tracker_node                        low_level_guard
                  ^       ^       ^                              ^
                  |       |       |                              |
             /lowstate  /odom  reference                    lease/candidate
                  |       |       |                              |
                  +-------+-------+                              |
                          |                                      |
                          v                                      |
                 431-dim observation                             |
                          |                                      |
                          v                                      |
                     latest.onnx                                 |
                          |                                      |
                          v                                      |
          29 x (q, dq, tau, kp, kd), Unitree order               |
                          |                                      |
                          +--> /g1/low_level/candidate -----------+
                                                                 |
                                                                 v
                                               lease/request/freshness/range
                                                     sequence/CRC checks
                                                                 |
                                                                 v
                                                              /lowcmd
                                                                 |
                                                                 v
                                                       Unitree 低层控制器
```

选择 `textop` 时，`/g1/safe_cmd/loco` 即使仍存在于 ROS graph 中也不得产生 Sport API
运动请求。系统不得同时依赖官方 Loco controller 来保持平衡。

## TextOp 启动准入

TextOp 控制链路只有满足以下条件才可接受 `ExecuteMotion`：

1. 静态配置选择 `motion.backend=textop`；
2. 机器人原生模式已由部署流程设置为允许 `/lowcmd` 控制的模式；
3. `/lowstate` 新鲜且至少包含 29 个有效 motor state；
4. `/odom` 提供与 manifest `anchor_body=pelvis` 一致的位置和速度；
5. DAR、VAE、normalization、CLIP 和 ONNX 均通过 manifest SHA-256 校验；
6. Tracker ONNX ABI 为 `obs[1,431] -> actions[1,29]`；
7. `low_level_guard` robot/control profile 与 manifest 完全一致；
8. 系统内 `/lowcmd` publisher 只有 `low_level_guard`。

准入失败时不得申请 low-level lease。已经申请 lease 后任一运行条件失效，应由 freshness
门控停止新的 `/lowcmd`，并终止当前 Action。

## 请求与停止语义

### Official Loco

`stop` 转换为 Sport API 零速度/停止请求。Sport command watchdog 负责动作持续时间和停止
确认。

### TextOp

TextOp 的 `stop` 和 `cancel` 必须统一映射为当前 `ExecuteMotion` Action 的 cancel：

```text
cancel Action
    -> generation token 失效
    -> 丢弃迟到的 GPU 结果
    -> 撤销 LowLevelControlLease
    -> Tracker 清空 reference/frame/last_action
    -> low_level_guard 停止发布新的 /lowcmd
```

不能只发送 Sport API 零速度来停止 TextOp。自然结束、用户取消、状态超时和模型异常最终
都必须经过同一撤租流程。

## 故障策略

系统不做跨 backend 自动故障转移：

- `official_loco` 故障时，不自动启动 TextOp；
- `textop` 故障时，不自动恢复 Sport/Loco；
- backend 节点异常退出时，启动监管器可以重启同一 backend，但不能改变 backend 类型；
- TextOp candidate、lease 或 lowstate 过期时，`low_level_guard` 停止产生 `/lowcmd`；
- 恢复控制必须由操作者修复问题并重新启动对应配置。

该策略避免在机器人运行中发生未确认的控制器、关节顺序和模式切换。

## 配置与启动接口

最终系统启动入口应只暴露一个 backend 参数：

```bash
ros2 launch g1_bringup g1_system.launch.py motion_backend:=official_loco
ros2 launch g1_bringup g1_system.launch.py motion_backend:=textop
```

推荐将 backend 配置同时写入启动日志和诊断状态：

```text
configured_backend=textop
runtime_switching=false
control_output=/lowcmd
```

不提供如下运行时接口：

- `/g1/motion/switch_backend`；
- backend toggle topic；
- 动作请求中的隐式自动选择；
- TextOp 失败后回退到 `official_loco`。

`ExecuteMotion.backend_id` 仍保留为请求一致性检查。它必须等于启动配置选择的 backend，
不能用来触发切换。

## 启动验证

### 通用检查

- 配置值只属于允许集合；
- 实际启动节点与启动矩阵一致；
- backend 值在进程生命周期内不变；
- stop 能到达当前 backend；
- 非当前 backend 的请求被拒绝。

### Official Loco 检查

- `/g1/safe_cmd/loco` 能产生 `/api/sport/request`；
- ROS graph 中不存在项目 `/lowcmd` publisher；
- TextOp Action Server 不存在。

### TextOp 检查

- 普通 loco intent 不产生 `/api/sport/request`；
- TextOp Action 能产生 reference、lease 和 candidate；
- `/lowcmd` 只有 `low_level_guard` 一个 publisher；
- 缺失 `/odom`、过期 `/lowstate` 或 manifest 不匹配时不产生 `/lowcmd`；
- stop/cancel 后 lease 被撤销，迟到生成结果不再进入 Tracker；
- 运行期间尝试改变 backend 配置不会改变控制链路。

## 实现边界

本文只确定静态选择架构，不授权实现运行时 MotionBackendManager。后续模型 A/B/C 如果也是
文本到低层执行的配套模型，应作为新的静态 backend 注册，并遵守相同互斥、准入和停止
契约：

```text
motion.backend:
  official_loco
  textop
  model_a
  model_b
  model_c
```

新增 backend 不能改变“一个启动实例只有一个全身运动控制输出所有者”的原则。
