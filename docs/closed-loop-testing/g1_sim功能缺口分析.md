# g1_sim 功能缺口分析与改进建议

**日期**: 2026-07-06  
**状态**: 分析阶段  
**版本**: 1.0

## 1. 执行摘要

g1_sim 作为 Unitree G1 原生主题的仿真器，当前已实现约 **80% 的 P0 功能**，能够支撑基本的闭环测试。但在仿真精度、API完整性和异常场景模拟方面存在若干缺口，需要进一步完善以支持全面的系统测试。

### 1.1 当前完成度评估

| 功能模块 | 完成度 | 优先级 | 阻塞程度 |
|---------|--------|--------|----------|
| 基础状态发布 | ✅ 95% | P0 | 无 |
| Sport API | ✅ 90% | P0 | 低 |
| Voice API | ✅ 95%+ | P0 | 基本完成 |
| 运动学模型 | ⚠️ 60% | P0 | 中 |
| 异常场景模拟 | ❌ 20% | P1 | 中 |
| Arm API | ⚠️ 50% | P1 | 低 |
| Dex3 手部 | ⚠️ 70% | P2 | 低 |

## 2. 详细功能缺口分析

### 2.1 关键问题

#### 2.1.1 Dex3 手部状态消息数组大小问题 🔴 高优先级

**问题描述**:
```python
# node.py:286-287
# TODO(g1_sim): allocate unbounded HandState arrays before filling Dex3 state.
motors = list(getattr(msg, "motor_state", []))[: self.state.hand_motor_count]
```

**影响范围**:
- Dex3 手部状态可能不完整
- 测试时可能导致 `IndexError` 或数据截断
- 影响 P2 阶段的手部控制测试

**根因分析**:
`unitree_hg/msg/HandState` 消息中的 `motor_state` 和 `press_sensor_state` 数组可能需要预分配，但当前实现假设数组已经预分配。

**解决方案**:
1. **短期**: 在配置中明确声明数组大小
2. **长期**: 实现动态数组分配逻辑
3. **验证**: 在单元测试中验证数组完整性

```python
# 建议的修复
def _make_hand_state(self, side: str) -> HandState:
    msg = self.msg["HandState"]()
    # 确保数组大小足够
    if hasattr(msg, "motor_state") and len(msg.motor_state) < self.state.hand_motor_count:
        # 预分配数组或扩展到所需大小
        pass
    # ... 现有逻辑
```

#### 2.1.2 运动学模型过于简化 🟡 中优先级

**当前实现**:
```python
# model.py:100-118
def integrate(self, now_sec: float) -> None:
    # 简单的匀速运动积分
    dt = max(0.0, active_until - self.last_update_sec)
    if dt > 0.0:
        cos_yaw = math.cos(self.yaw)
        sin_yaw = math.sin(self.yaw)
        self.x += (cos_yaw * self.vx - sin_yaw * self.vy) * dt
        self.y += (sin_yaw * self.vx + cos_yaw * self.vy) * dt
        self.yaw = _wrap_angle(self.yaw + self.vyaw * dt)
```

**缺失功能**:
- ❌ 加速度限制
- ❌ 加加速度 (jerk) 限制
- ❌ 动态响应延迟
- ❌ 机器人动力学特性 (质量、惯性)
- ❌ 地面摩擦和打滑模拟
- ❌ 姿态稳定性检查

**影响**:
- 无法测试真实的加速度限制
- 无法验证连续性检查的有效性
- 仿真与真机行为差异大

**建议改进**:
```python
@dataclass
class SimulatedRobotState:
    # 现有字段...
    max_acceleration: float = 2.0  # m/s²
    max_jerk: float = 5.0  # m/s³
    reaction_delay_sec: float = 0.1  # 反应延迟
    
    def apply_velocity_command(self, params: dict, now_sec: float):
        # 实现加速度限制
        # 实现延迟响应
        # 实现动力学约束
        pass
```

#### 2.1.3 Sport API 缺失部分功能 🟡 中优先级

**已实现的 API IDs**:
```python
# config.py:48-63
"sport_api_ids": {
    "get_fsm_id": 7001,          # ✅ 已实现
    "get_fsm_mode": 7002,        # ✅ 已实现
    "get_balance_mode": 7003,    # ✅ 已实现
    "get_swing_height": 7004,    # ✅ 已实现
    "get_stand_height": 7005,    # ✅ 已实现
    "get_phase": 7006,           # ✅ 已实现
    "set_fsm_id": 7101,          # ✅ 已实现
    "set_balance_mode": 7102,     # ✅ 已实现
    "set_swing_height": 7103,    # ✅ 已实现
    "set_stand_height": 7104,    # ✅ 已实现
    "set_velocity": 7105,        # ✅ 已实现
    "set_arm_task": 7106,        # ⚠️ 部分实现
    "set_speed_mode": 7107,      # ✅ 已实现
    "switch_to_user_ctrl": 7110, # ✅ 已实现
    "switch_to_internal_ctrl": 7111, # ✅ 已实现
}
```

**缺失或不完整的功能**:
- ⚠️ `set_arm_task`: 仅记录任务ID，未实际影响手臂状态
- ❌ `get_dq` / `get_ddq`: 未实现速度和加速度查询
- ❌ `get_body_pose`: 未实现姿态查询
- ❌ 连续运动路径插值

**影响**:
- 无法测试复杂的运动序列
- 手臂与行走协调测试受限

#### 2.1.4 Voice API 高保真模拟仍可增强 🟢 低优先级

**当前实现**:
```python
# model.py:244-318
def handle_voice_api(...):
    if action == "tts":
        payload = {..., "accepted": True}  # 始终接受
    elif action == "asr":
        payload = {..., "text": default_asr_text}  # 固定文本
    elif action == "start_play":
        state.active_playback[app_name] = {...}  # ✅ 记录播放状态
        payload = {..., "status": "playing"}
    elif action == "stop_play":
        playback = state.active_playback.pop(app_name, None)  # ✅ 停止指定应用
        payload = {..., "stopped_streams": stopped_streams}
    elif action == "set_volume":
        state.volume = max(0, min(100, int(...)))  # ✅ 正常
    elif action == "set_rgb_led":
        payload = {...}  # 仅返回参数，无实际效果
```

**已补齐功能**:
- ✅ `start_play` (1003): 接收 `app_name` 和 `stream_id`，记录到 `active_playback`，返回 `status: "playing"`，并写入带时间戳的 `playback_history`
- ✅ `stop_play` (1004): 接收 `app_name`，移除对应播放记录，返回 `stopped_streams`，并写入停止时间戳
- ✅ 支持多应用独立播放状态记录
- ✅ 支持不存在 app、空 `app_name` 等边界场景

**剩余增强项**:
- ❌ TTS 实际播放时间模拟
- ❌ 音量变化对 ASR 的影响
- ❌ LED 状态持久化
- ❌ ASR 失败场景模拟

**建议改进**:
```python
@dataclass
class SimulatedRobotState:
    # 现有字段...
    tts_playing: bool = False
    tts_remaining_sec: float = 0.0
    led_color: tuple = (0, 0, 0)
    led_ttl_sec: float = 0.0
    
    def handle_tts(self, text: str, now_sec: float):
        # 估算播放时间 (字数 / 语速)
        self.tts_playing = True
        self.tts_remaining_sec = len(text) * 0.1  # 假设每字0.1秒
        
    def integrate(self, now_sec: float):
        # 现有逻辑...
        # TTS 播放计时
        if self.tts_playing:
            dt = now_sec - self.last_update_sec
            self.tts_remaining_sec -= dt
            if self.tts_remaining_sec <= 0:
                self.tts_playing = False
```

### 2.2 异常场景模拟缺失

当前 g1_sim 主要模拟正常工作场景，缺少以下异常情况的模拟：

| 异常类型 | 优先级 | 当前状态 | 建议实现 |
|---------|--------|---------|---------|
| 状态消息丢失 | P1 | ❌ 未实现 | 定期停止发布 lowstate |
| API 响应超时 | P1 | ❌ 未实现 | 随机延迟或不响应 |
| API 响应错误码 | P1 | ❌ 未实现 | 返回非零 code |
| 电机过热 | P1 | ❌ 未实现 | temperature > 阈值 |
| 电池低压 | P1 | ❌ 未实现 | battery_voltage < 阈值 |
| 通信丢失 | P0 | ⚠️ 部分实现 | 完整的断连模拟 |
| 电机 lost | P1 | ❌ 未实现 | motor_state[].lost = 1 |
| IMU 异常 | P1 | ❌ 未实现 | 异常姿态/角速度 |
| 运动冲突 | P2 | ❌ 未实现 | 低层/高层冲突检测 |

**建议的异常模拟接口**:
```python
@dataclass  
class SimulatedRobotState:
    # 现有字段...
    fault_injection: dict = field(default_factory=dict)
    
    def inject_fault(self, fault_type: str, **params):
        """注入测试故障"""
        self.fault_injection[fault_type] = params
        
    def check_faults(self, now_sec: float):
        """检查并应用故障条件"""
        if "motor_overheat" in self.fault_injection:
            # 设置电机温度过热
            pass
        if "api_timeout" in self.fault_injection:
            # 延迟或跳过 API 响应
            pass
```

### 2.3 配置和验证问题

#### 2.3.1 缺少验证模式

**问题**: g1_sim 没有专门的"验证模式"，难以确认仿真是否按预期工作。

**建议**: 添加验证模式和诊断接口

```python
class G1SimNode:
    def __init__(self, node, config):
        # 现有初始化...
        if config.sim.get("validation_mode", False):
            self.validation_pub = node.create_publisher(
                String, "/g1_sim/validation", 10
            )
            node.create_timer(1.0, self.publish_validation_status)
            
    def publish_validation_status(self):
        """发布仿真状态，便于测试验证"""
        status = {
            "sim_time": self._now_sec(),
            "robot_pose": self.state.snapshot(self._now_sec()),
            "pending_requests": len(self._pending_requests),
            "published_topics": self._get_published_topic_counts(),
        }
        self.validation_pub.publish(String(data=json.dumps(status)))
```

#### 2.3.2 配置灵活性不足

**问题**: 某些关键参数硬编码在代码中，难以调整测试场景。

**硬编码参数**:
- 电机数量 (35)
- 手部电机数量 (7)  
- 默认 FSM mode (2)
- 运动学积分步长

**建议**: 将这些参数移至配置文件

```python
# config.py
DEFAULT_CONFIG = {
    "sim": {
        # 现有配置...
        "fsm_defaults": {
            "default_fsm_id": 0,
            "default_fsm_mode": 2,
            "default_balance_mode": 0,
        },
        "kinematics": {
            "max_acceleration": 2.0,
            "max_jerk": 5.0,
            "reaction_delay_sec": 0.1,
        },
        "fault_injection": {
            "enabled": False,
            "motor_overheat_probability": 0.0,
            "api_timeout_probability": 0.0,
        }
    }
}
```

## 3. 优先级改进计划

### 3.1 P0 关键修复 (立即)

1. **修复 Dex3 数组大小问题** 🔴
   - 估计工作量: 2-4 小时
   - 风险: 低
   - 影响: 解除 P2 阻塞

2. **添加基本的异常模拟** 🟡
   - API 超时模拟
   - 状态丢失模拟  
   - 估计工作量: 4-6 小时
   - 风险: 低
   - 影响: 提升测试覆盖率

### 3.2 P1 功能增强 (1-2周内)

1. **改进运动学模型** 🟡
   - 加速度限制
   - 动态响应延迟
   - 估计工作量: 8-12 小时
   - 风险: 中
   - 影响: 仿真真实性提升

2. **增强 Voice API 高保真模拟** 🟢
   - TTS 播放时间模拟
   - LED 状态管理
   - ASR 失败场景模拟
   - 估计工作量: 2-4 小时
   - 风险: 低
   - 影响: 提升语音测试真实性

3. **Sport API 完善** 🟡
   - 姿态查询 API
   - 速度/加速度查询
   - 估计工作量: 6-8 小时
   - 风险: 中
   - 影响: 运动控制测试

### 3.3 P2 长期优化 (未来)

1. **故障注入框架**
   - 可配置的故障模式
   - 概率性故障注入
   - 估计工作量: 16-24 小时
   - 风险: 中
   - 影响: 压力测试能力

2. **高精度运动学**
   - 机器人动力学模型
   - 地面交互模拟
   - 姿态稳定性
   - 估计工作量: 40-60 小时
   - 风险: 高
   - 影响: 高保真仿真

## 4. 测试覆盖度分析

### 4.1 当前可测试的场景

✅ **已支持**:
- 基本运动指令 (前进、后退、转向)
- 模式切换 (用户/内部控制)
- 语音会话管理
- 音频播放控制 (`start_play` / `stop_play`)
- 基本安全限制检查
- 状态消息发布

### 4.2 当前难以测试的场景

❌ **受限或不支持**:
- 加速度限制验证
- 连续运动平滑性
- TTS 播放时长与运动协调
- 异常恢复流程
- 长时间运行稳定性
- 资源限制场景

### 4.3 测试建议

**立即可执行**:
1. 基本功能闭环测试
2. 安全限制验证测试
3. 模式切换测试
4. 语音行走测试

**等待改进后**:
1. 加速度限制测试
2. 异常恢复测试
3. 长期稳定性测试
4. 性能基准测试

## 5. 结论

g1_sim 当前状态**足以支持 P0 阶段的基本闭环测试**，但在以下方面需要改进：

### 5.1 必须修复 (阻塞P0测试)
- Dex3 手部数组问题
- 基本的异常场景模拟

### 5.2 强烈建议 (提升测试质量)
- 运动学模型改进
- Voice API 高保真模拟增强
- 配置灵活性提升

### 5.3 长期优化 (未来功能)
- 故障注入框架
- 高精度运动学
- 完整的 Arm API 支持

总体而言，g1_sim 的架构设计良好，扩展性强，通过渐进式改进可以成为一个功能完善的仿真环境。

## 6. 推荐行动

### 立即执行 (本周内)
1. 修复 Dex3 数组大小问题
2. 添加 API 超时和状态丢失模拟
3. 编写基本的验证测试
4. ✅ Voice API 音频播放控制已完成 (`start_play` / `stop_play`)

### 短期计划 (2-4周)
1. 改进运动学模型
2. 增加配置灵活性
3. 增强 Voice API 高保真模拟
4. 编写完整的测试用例

### 中期计划 (2-3个月)
1. 实现故障注入框架
2. 完善 Sport API
3. 性能优化和基准测试
4. 文档完善

通过分阶段的改进，g1_sim 将能够从当前的 **80% P0 完成度** 提升到 **95%+ P0/P1 完成度**，成为一个robust的仿真测试环境。
