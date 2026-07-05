# 安全控制节点 (Safety Control Node) 设计文档

**日期**: 2026-07-05  
**状态**: 设计阶段  
**优先级**: P0 (关键安全组件)

## 1. 背景

### 1.1 当前架构问题

当前 G1 Agent 系统存在安全架构缺陷：

```
Voice Bridge Node
    ↓
/voice/cmd/loco, /voice/cmd/action (未验证的命令)
    ↓
[缺失安全验证层]
    ↓
G1 Interface Node → /g1/safe_cmd/* (期望已验证的命令)
```

**核心问题**：
- Voice Bridge 输出的动作命令未经过安全验证
- 缺少机器人状态检查、模式验证、超时保护
- 没有集中管理运动限制和安全边界
- 音频/非动作命令与动作命令混用同一通道

### 1.2 设计目标

1. **安全验证**：所有动作命令必须通过多层安全检查
2. **状态感知**：基于机器人当前状态做出允许/拒绝决策
3. **超时保护**：防止过期命令执行
4. **速率限制**：防止命令堆积和失控
5. **审计追踪**：记录所有安全决策和命令历史

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Voice Bridge Node                           │
│  ┌──────────────────┐         ┌──────────────────┐            │
│  │ ASR Intent       │         │ Agent Decision   │            │
│  │ Processing       │         │ Engine           │            │
│  └────────┬─────────┘         └────────┬─────────┘            │
│           │                            │                       │
│           ├──────────┬─────────────────┤                       │
│           │          │                 │                       │
│           ↓          ↓                 ↓                       │
│    /g1/cmd/audio/*  /voice/cmd/loco  /voice/cmd/action        │
│    (直接连接)      (动作意图)       (动作意图)                  │
│           │          │                 │                       │
│           │    ┌─────┴─────────────────┴─────┐                │
│           │    │                               │                │
│           │    ↓                               ↓                │
│           │ ┌──────────────────────────────────────────┐      │
│           │ │          Safety Control Node             │      │
│           │ │  ┌────────────────────────────────────┐  │      │
│           │ │  │  多层安全验证引擎                  │  │      │
│           │ │  │  1. 机器人状态检查                │  │      │
│           │ │  │  2. 模式兼容性验证                │  │      │
│           │ │  │  3. 运动限制检查                  │  │      │
│           │ │  │  4. 超时和速率限制                │  │      │
│           │ │  │  5. 紧急停止处理                  │  │      │
│           │ │  └────────────────────────────────────┘  │      │
│           │ └───────────────────┬──────────────────────┘      │
│           │                     │                              │
│           │                     ↓                              │
│           │            /g1/safe_cmd/loco                      │
│           │            /g1/safe_cmd/stop                      │
│           │                     │                              │
│           └─────────────────────┼──────────────────────────────┘
│                                 │
└─────────────────────────────────┼─────────────────────────────┘
                                  ↓
                    ┌───────────────────────────────────────┐
                    │         G1 Interface Node            │
                    │  ┌─────────────────────────────────┐  │
                    │  │  安全命令执行                    │  │
                    │  │  - 转换为 Sport API 请求         │  │
                    │  │  - 发布到 Unitree 原生主题      │  │
                    │  └─────────────────────────────────┘  │
                    └───────────────────────────────────────┘
                                  ↓
                    ┌───────────────────────────────────────┐
                    │         Unitree G1 Robot              │
                    └───────────────────────────────────────┘
```

### 2.2 关键设计原则

1. **音频直通，动作拦截**：
   - ASR/TTS/LED 等音频相关命令直接连接到 G1 Interface
   - 只有 `loco`（运动）和 `action`（动作）命令需要安全验证

2. **安全边界清晰**：
   - Safety Control Node 是唯一的动作命令验证点
   - 所有安全逻辑集中在一个节点，便于审查和维护

3. **失败安全**：
   - 任何安全检查失败都拒绝命令
   - 验证超时默认拒绝
   - 传感器数据缺失时进入安全状态

## 3. 安全验证机制

### 3.1 多层验证流程

```python
def validate_command(command: Command, robot_state: RobotState) -> SafetyDecision:
    """多层安全验证流程"""
    
    # 第1层：基础健康检查
    if not robot_state.is_healthy():
        return SafetyDecision.REJECT("机器人状态异常")
    
    # 第2层：传感器时效性检查
    if robot_state.is_state_stale():
        return SafetyDecision.REJECT("传感器数据过期")
    
    # 第3层：机器人模式检查
    if not is_mode_compatible(command, robot_state.mode):
        return SafetyDecision.REJECT("机器人模式不兼容")
    
    # 第4层：命令时效性检查
    if command.is_expired():
        return SafetyDecision.REJECT("命令已过期")
    
    # 第5层：速率限制检查
    if rate_limiter.is_exceeded():
        return SafetyDecision.REJECT("命令速率超限")
    
    # 第6层：运动学限制检查（仅运动命令）
    if command.kind == "loco":
        if not check_motion_limits(command.params):
            return SafetyDecision.REJECT("运动参数超限")
        
        if not check_velocity_continuity(command.params, robot_state):
            return SafetyDecision.REJECT("速度变化过快")
    
    # 第7层：特殊动作权限检查（仅动作命令）
    if command.kind == "action":
        if not check_action_permission(command.params["action"]):
            return SafetyDecision.REJECT("动作未授权")
    
    # 所有检查通过
    return SafetyDecision.ALLOW()
```

### 3.2 机器人状态检查

**健康状态指标**：
- `lowstate` 年龄 < 300ms
- IMU 数据正常
- 电机温度正常 (< 60°C)
- 无故障或错误状态

**模式兼容性矩阵**：

| 命令类型 | Sport API 模式 | 用户控制模式 | 说明 |
|---------|---------------|-------------|------|
| `loco`  | ✅ 允许 | ❌ 拒绝 | 运动命令仅允许在 Sport API 模式 |
| `stop`  | ✅ 允许 | ✅ 允许 | 停止命令允许在任何模式 |
| `cancel` | ✅ 允许 | ✅ 允许 | 取消命令允许在任何模式 |

### 3.3 运动学限制

**速度限制**（已在 G1 Interface 中实现，但在此进行二次验证）：

```python
MOTION_LIMITS = {
    "vx": {"min": -0.5, "max": 0.5, "rate_limit": 0.3},  # m/s, 最大变化率
    "vy": {"min": -0.3, "max": 0.3, "rate_limit": 0.2},  # m/s
    "vyaw": {"min": -0.8, "max": 0.8, "rate_limit": 0.4},  # rad/s
    "duration_sec": {"min": 0.01, "max": 2.0},
}

# 速度连续性检查：防止突变
def check_velocity_continuity(new_params, current_velocity):
    for axis in ["vx", "vy", "vyaw"]:
        new_val = new_params[axis]
        current_val = current_velocity[axis]
        rate_limit = MOTION_LIMITS[axis]["rate_limit"]
        
        if abs(new_val - current_val) > rate_limit:
            return False
    return True
```

**加速度和加加速度限制**：
- 最大加速度：2.0 m/s²
- 最大加加速度：5.0 m/s³

### 3.4 超时和速率限制

**命令超时**：
- 命令生成到执行的最大延迟：100ms
- 超过此时间的命令自动拒绝

**速率限制**：
```python
RATE_LIMITS = {
    "loco": {"max_per_second": 5, "burst": 3},    # 每秒最多5个，突发3个
    "stop": {"max_per_second": 10, "burst": 10},  # 停止命令优先级更高
    "action": {"max_per_second": 3, "burst": 2},
}
```

### 3.5 紧急停止处理

**无条件接受的命令**：
- `stop` / `cancel` 动作（优先级最高）
- 电池电压 < 安全阈值时自动停止
- 检测到跌倒或碰撞时自动停止
- 看门狗超时时自动停止

## 4. 接口定义

### 4.1 订阅主题（输入）

**来自 Voice Bridge 的动作意图**：
```yaml
/voice/cmd/loco:
  type: std_msgs/msg/String
  description: 语音意图的运动命令（JSON格式）
  schema:
    source: str              # "voice_bridge"
    session_id: str         # 会话ID
    command_id: str         # 命令ID
    text: str               # 原始语音文本
    vx: float               # X方向速度
    vy: float               # Y方向速度
    vyaw: float             # 偏航角速度
    duration_sec: float     # 持续时间

/voice/cmd/action:
  type: std_msgs/msg/String
  description: 语音意图的动作命令（JSON格式）
  schema:
    source: str
    session_id: str
    command_id: str
    action: str             # "stop", "cancel", etc.
    priority: str           # "normal", "emergency"
    text: str
```

**来自 G1 Interface 的状态反馈**：
```yaml
/g1/state/mode:
  type: std_msgs/msg/String
  description: 机器人当前模式（JSON格式）

/g1/state/safety:
  type: std_msgs/msg/String
  description: 安全状态信息（如已实现）

/g1/state/health:
  type: diagnostic_msgs/msg/DiagnosticArray
  description: 机器人健康状态
```

**可选：直接订阅低层状态**（用于更精确的决策）：
```yaml
/g1/state/low:
  type: std_msgs/msg/String
  description: 低状态摘要（电机状态、温度等）
```

### 4.2 发布主题（输出）

**验证通过的安全命令**：
```yaml
/g1/safe_cmd/loco:
  type: std_msgs/msg/String
  description: 验证通过的运动命令
  schema: 与 /voice/cmd/loco 相同，但添加验证元数据

/g1/safe_cmd/stop:
  type: std_msgs/msg/String
  description: 验证通过的停止命令
```

**安全决策日志**：
```yaml
/g1/safety/decisions:
  type: std_msgs/msg/String
  description: 所有安全决策的审计日志
  schema:
    timestamp: float
    command_id: str
    command_kind: str        # "loco", "action"
    decision: str            # "allow", "reject"
    reason: str              # 拒绝原因或空
    validation_time_ms: float
    robot_state: dict        # 决策时的机器人状态快照
```

### 4.3 服务接口（可选）

```yaml
# 紧急停止服务
/g1/safety/emergency_stop:
  type: std_srvs/srv/Empty
  description: 立即停止所有运动

# 配置更新服务
/g1/safety/update_limits:
  type: unitree_g1_agent/srv/UpdateSafetyLimits
  description: 动态更新安全限制参数

# 获取安全状态服务
/g1/safety/get_status:
  type: unitree_g1_agent/srv/SafetyStatus
  response:
    is_healthy: bool
    active_session_count: int
    rejection_rate: float
    last_rejection_reason: str
```

## 5. 数据结构

### 5.1 安全决策结果

```python
@dataclass(frozen=True)
class SafetyDecision:
    """安全验证结果"""
    allowed: bool
    reason: str | None = None
    modified_params: dict[str, Any] | None = None
    check_details: dict[str, bool] | None = None
    
    @classmethod
    def allow(cls) -> "SafetyDecision":
        return cls(allowed=True, reason=None)
    
    @classmethod
    def reject(cls, reason: str) -> "SafetyDecision":
        return cls(allowed=False, reason=reason)
```

### 5.2 命令包装器

```python
@dataclass
class ValidatedCommand:
    """经过验证的命令"""
    original_command: dict
    validation_timestamp: float
    safety_decision: SafetyDecision
    robot_state_snapshot: dict
    
    def to_safe_command(self) -> str:
        """转换为安全命令JSON"""
        payload = dict(self.original_command)
        payload["validated_at"] = self.validation_timestamp
        payload["validation_result"] = {
            "allowed": self.safety_decision.allowed,
            "reason": self.safety_decision.reason,
        }
        return json.dumps(payload, ensure_ascii=False)
```

### 5.3 机器人状态快照

```python
@dataclass
class RobotStateSnapshot:
    """机器人当前状态快照"""
    timestamp: float
    mode: str | None
    health_state: str  # "ok", "degraded", "unhealthy"
    lowstate_age_ms: int | None
    current_velocity: dict[str, float]  # {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}
    motor_count: int
    max_temperature: float | None
    
    def is_healthy(self) -> bool:
        """综合健康检查"""
        return (
            self.health_state == "ok" and
            self.lowstate_age_ms is not None and
            self.lowstate_age_ms < 300 and
            (self.max_temperature is None or self.max_temperature < 60.0)
        )
    
    def is_state_stale(self) -> bool:
        """检查状态是否过期"""
        return self.lowstate_age_ms is None or self.lowstate_age_ms > 300
```

## 6. 配置管理

### 6.1 配置文件结构

```yaml
# safety_control.yaml

safety:
  # 全局开关
  enabled: true
  strict_mode: true  # true时，任何不确定都拒绝
  require_command_timestamp: true
  
  # 超时配置
  command_timeout_ms: 100
  state_timeout_ms: 300
  
  # 速率限制
  rate_limits:
    loco:
      max_per_second: 5
      burst: 3
    stop:
      max_per_second: 10
      burst: 10
    action:
      max_per_second: 3
      burst: 2

  # 运动限制
  motion_limits:
    vx:
      min: -0.5
      max: 0.5
      rate_limit: 0.3  # 最大变化率
    vy:
      min: -0.3
      max: 0.3
      rate_limit: 0.2
    vyaw:
      min: -0.8
      max: 0.8
      rate_limit: 0.4
    duration_sec:
      min: 0.01
      max: 2.0

  # 速度连续性检查
  velocity_continuity:
    enabled: true
    max_acceleration: 2.0  # m/s²
    max_jerk: 5.0  # m/s³

  # 模式限制
  mode_restrictions:
    sport_api_loco:
      allow_loco: true
      allow_action_stop: true
      allow_action_cancel: true
    user_ctrl:
      allow_loco: false
      allow_action_stop: true
      allow_action_cancel: true
    armed_mode:
      allow_loco: false
      allow_action_stop: true
      allow_action_cancel: true

  # 健康检查阈值
  health_thresholds:
    max_lowstate_age_ms: 300
    max_motor_temperature: 60.0
    require_motor_temperature: false
    min_battery_voltage: 42.0  # V
    require_battery_voltage: false
    
  # 审计和日志
  audit:
    log_all_decisions: true
    log_rejected_only: false
    retain_days: 30

# 主题映射
topics:
  input:
    loco_intent: /voice/cmd/loco
    action_intent: /voice/cmd/action
    robot_mode: /g1/state/mode
    safety_state: /g1/state/safety
    health: /g1/state/health
    lowstate: /g1/state/low  # 可选
  
  output:
    safe_loco: /g1/safe_cmd/loco
    safe_stop: /g1/safe_cmd/stop
    decisions: /g1/safety/decisions
```

### 6.2 动态配置更新

支持运行时更新以下参数（通过服务或参数）：
- 运动限制（`motion_limits.*`）
- 速率限制（`rate_limits.*`）
- 健康检查阈值（`health_thresholds.*`）

## 7. 实现细节

### 7.1 核心组件

```python
class SafetyControlNode:
    """安全控制节点主类"""
    
    def __init__(self, node, config):
        self.node = node
        self.config = config
        self.robot_state = RobotStateTracker()
        self.rate_limiters = {
            "loco": RateLimiter(**config.rate_limits["loco"]),
            "action": RateLimiter(**config.rate_limits["action"]),
            "stop": RateLimiter(**config.rate_limits["stop"]),
        }
        self.validator = SafetyValidator(config)
        self.audit_logger = AuditLogger(config.audit)
        
    def on_loco_intent(self, msg):
        """处理运动意图"""
        try:
            intent = parse_loco_intent(msg.data)
            decision = self.validator.validate_loco(
                intent, 
                self.robot_state.get_snapshot()
            )
            
            if decision.allowed:
                self.publish_safe_loco(intent, decision)
            else:
                self.log_rejection(intent, decision)
                
        except Exception as exc:
            self.node.get_logger().error(f"处理失败: {exc}")
    
    def on_action_intent(self, msg):
        """处理动作意图"""
        try:
            intent = parse_action_intent(msg.data)
            decision = self.validator.validate_action(
                intent,
                self.robot_state.get_snapshot()
            )
            
            # stop/cancel 优先级高，跳过速率限制
            if intent.action in {"stop", "cancel"}:
                if decision.allowed:
                    self.publish_safe_action(intent, decision)
            else:
                if decision.allowed and self.rate_limiters["action"].check():
                    self.publish_safe_action(intent, decision)
                else:
                    self.log_rejection(intent, decision)
                    
        except Exception as exc:
            self.node.get_logger().error(f"处理失败: {exc}")
```

### 7.2 机器人状态跟踪器

```python
class RobotStateTracker:
    """跟踪机器人当前状态"""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._current_state = None
        self._last_update = None
        self._current_velocity = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}
        
    def update_from_health(self, health_msg):
        """从健康消息更新状态"""
        with self._lock:
            self._last_update = time.time()
            # 解析 health 消息...
            self._current_state = RobotStateSnapshot(...)
    
    def update_from_lowstate(self, lowstate_msg):
        """从低状态更新速度信息"""
        with self._lock:
            # 提取当前速度...
            self._current_velocity = extract_velocity(lowstate_msg)
    
    def get_snapshot(self) -> RobotStateSnapshot:
        """获取当前状态快照"""
        with self._lock:
            if self._current_state is None:
                # 返回不健康状态
                return RobotStateSnapshot.unhealthy()
            return self._current_state
```

### 7.3 安全验证器

```python
class SafetyValidator:
    """执行多层安全验证"""
    
    def __init__(self, config):
        self.config = config
        self.checks = [
            HealthCheck(config.health_thresholds),
            ModeCheck(config.mode_restrictions),
            TimeoutCheck(config.command_timeout_ms),
            MotionLimitsCheck(config.motion_limits),
            VelocityContinuityCheck(config.velocity_continuity),
        ]
    
    def validate_loco(self, intent, robot_state) -> SafetyDecision:
        """验证运动命令"""
        for check in self.checks:
            result = check.validate_loco(intent, robot_state)
            if not result.allowed:
                return result
        return SafetyDecision.allow()
    
    def validate_action(self, intent, robot_state) -> SafetyDecision:
        """验证动作命令"""
        # stop/cancel 只需基础检查
        if intent.action in {"stop", "cancel"}:
            return SafetyDecision.allow()
        
        # 其他动作需要完整验证
        for check in self.checks:
            result = check.validate_action(intent, robot_state)
            if not result.allowed:
                return result
        return SafetyDecision.allow()
```

## 8. 测试策略

### 8.1 单元测试

**测试用例类别**：

1. **健康检查测试**：
   - 正常状态允许命令
   - 状态过期拒绝命令
   - 高温拒绝命令
   - 传感器缺失拒绝命令

2. **模式验证测试**：
   - Sport API 模式允许运动
   - 用户控制模式拒绝运动
   - 停止命令在所有模式允许

3. **运动限制测试**：
   - 速度边界测试
   - 持续时间边界测试
   - 速度连续性测试

4. **速率限制测试**：
   - 正常速率允许
   - 超过速率拒绝
   - 突发处理测试

5. **超时测试**：
   - 新命令允许
   - 过期命令拒绝

### 8.2 集成测试

**端到端场景**：

```bash
# 场景1：正常运动命令流程
1. 模拟 ASR 输入 "向前走一秒"
2. 验证 Safety Control Node 接收意图
3. 验证安全检查通过
4. 验证 G1 Interface 收到安全命令
5. 验证 Sport API 请求正确

# 场景2：模式不兼容拒绝
1. 切换机器人到用户控制模式
2. 发送运动意图
3. 验证命令被拒绝
4. 验证拒绝日志记录

# 场景3：传感器数据过期
1. 停止 lowstate 发布
2. 等待超时
3. 发送运动意图
4. 验证命令被拒绝
5. 验证拒绝原因为 "传感器数据过期"

# 场景4：紧急停止
1. 发送运动命令序列
2. 发送停止命令
3. 验证停止命令优先处理
4. 验证后续运动命令被取消
```

### 8.3 安全测试

**故障注入测试**：

- 网络延迟模拟（高延迟应拒绝命令）
- 丢包模拟（应拒绝过期命令）
- 状态消息丢失（应拒绝命令）
- 并发命令冲击（速率限制应生效）

## 9. 部署和运行

### 9.1 依赖关系

```
启动顺序：
1. Unitree 原生节点（提供 /lowstate, /api/*）
2. G1 Interface Node（提供 /g1/state/*）
3. Safety Control Node（提供 /g1/safe_cmd/*）
4. Voice Bridge Node（发布 /voice/cmd/*）
```

### 9.2 启动命令

```bash
# 启动安全控制节点
ros2 launch safety_control safety_control.launch.py \
  config_path:=src/safety_control/config/safety_control.yaml

# 验证运行状态
ros2 topic echo /g1/safety/decisions
ros2 topic echo /g1/safe_cmd/loco
```

### 9.3 监控和调试

**关键监控指标**：
- 命令通过率
- 命令拒绝率和原因分布
- 平均验证延迟
- 机器人状态健康度

**调试技巧**：
```bash
# 查看所有安全决策
ros2 topic echo /g1/safety/decisions --csv

# 查看当前机器人状态
ros2 topic echo /g1/state/mode

# 查看健康状态
ros2 topic echo /g1/state/health

# 模拟语音意图
ros2 topic pub /voice/cmd/loco std_msgs/msg/String \
  '{data: "{\"vx\":0.2,\"vy\":0.0,\"vyaw\":0.0,\"duration_sec\":1.0}"}'
```

## 10. 风险和限制

### 10.1 已知限制

1. **单点故障**：Safety Control Node 故障会导致所有命令被拒绝
2. **延迟增加**：每条命令增加 1-5ms 验证延迟
3. **配置复杂**：需要正确配置多个安全参数

### 10.2 缓解措施

1. **健康监控**：对 Safety Control Node 本身进行健康检查
2. **看门狗**：如果 Safety Control Node 无响应，自动拒绝所有命令
3. **配置验证**：启动时验证所有配置参数
4. **降级模式**：如果验证失败，进入安全模式（仅允许停止）

### 10.3 未来增强

1. **预测性安全**：基于轨迹预测未来的碰撞风险
2. **自适应限制**：根据环境动态调整速度限制
3. **机器学习**：学习异常命令模式
4. **视觉融合**：集成摄像头数据进行障碍物检测

## 11. 验收标准

安全控制节点被认为完成并可用于生产环境，当满足以下标准：

- [ ] 所有单元测试通过（>90% 代码覆盖率）
- [ ] 所有集成测试场景通过
- [ ] 安全测试无关键缺陷
- [ ] 平均验证延迟 < 5ms
- [ ] 99.9% 的有效命令在 100ms 内通过验证
- [ ] 拒绝的命令都有明确的可审计原因
- [ ] 配置文档完整且经过验证
- [ ] 运维手册完成
- [ ] 代码审查通过
- [ ] 安全专家审查通过

---

**文档版本**: 1.0  
**最后更新**: 2026-07-05  
**作者**: Claude Code (Unitree G1 Agent 项目)
