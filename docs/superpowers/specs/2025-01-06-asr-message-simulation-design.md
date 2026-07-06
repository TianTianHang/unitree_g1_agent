# ASR消息模拟修复设计

**日期**: 2026-07-06
**状态**: 待实现，已通过Codex审查
**相关包**: `src/g1_sim`

---

## 问题陈述

当前g1_sim模拟器中的ASR消息模拟存在两个关键问题：

### 问题1：ASR消息格式错误
**当前行为**: 只发布原始文本字符串到`/audio_msg` topic
```python
msg.data = "模拟 ASR 文本"
```

**期望行为**: 发布完整的JSON对象，符合Unitree G1官方文档格式
```json
{
  "index": 1,
  "timestamp": 29319303490,
  "text": "你好",
  "angle": 90,
  "speaker_id": 0,
  "sense": "unknown",
  "confidence": 0.95,
  "language": "zh-CN",
  "is_final": true
}
```

### 问题2：缺少play_state消息
**期望行为**: 当语音播放状态发生变化时，应发布play_state消息
```json
{"play_state": 1}  // 开始播放
{"play_state": 0}  // 停止播放
```

**当前行为**: 播放状态变化时没有发布任何消息

---

## 设计方案

### 核心思路

采用**事件驱动**的方式模拟真实硬件的ASR行为：
- 新增订阅topic `~/asr_input` 作为"模拟麦克风输入"
- 当收到文本时，包装成标准ASR JSON发布到`/audio_msg`
- 支持`~/asr_input`和`asr` API两种触发方式，共用同一发布逻辑

### 架构变更

```
新增订阅：~/asr_input (std_msgs/msg/String)
              ↓
    _on_asr_input_callback(text)
              ↓
    publish_asr_message(text) → JSON格式ASR消息
              ↓
    audio_msg_pub.publish(JSON)
```

### 并行路径

```
asr API调用 (api_id=1002)
              ↓
    on_voice_request() 
              ↓
    publish_asr_message(text) → 同样的JSON格式
              ↓
    audio_msg_pub.publish(JSON)
```

---

## 详细设计

### 1. Topic命名

**决策**: `~/asr_input`

**理由**:
- 节点私有topic，符合ROS2最佳实践
- 展开后为`/g1_sim/asr_input`（假设节点名为`g1_sim`）
- 支持节点重命名、多实例仿真
- 不会污染全局命名空间

**测试方式**:
```bash
ros2 topic pub /g1_sim/asr_input std_msgs/msg/String "data: '测试语音'"
```

### 2. 消息类型

**决策**: `std_msgs/msg/String`

**理由**:
- 当前需求只需传递文本
- ASR JSON的9个字段由g1_sim统一补齐默认值
- 避免增加自定义消息的构建复杂度
- 易于通过命令行测试

**未来扩展**: 如需控制confidence、speaker_id等参数，可增加`~/asr_input_json`高级入口

### 3. 优先级处理

**决策**: 两个输入源都触发ASR消息发布

**理由**:
- `~/asr_input` 和 `asr` API 是两个独立的触发器
- 仿真器行为应该是"收到一次输入，产生一次ASR事件"
- 两个入口共用同一个`publish_asr_message()`函数
- 格式逻辑只有一份，行为直观

### 4. ASR消息字段

基于用户需求和Codex决策，ASR消息字段定义如下：

| 字段 | 类型 | 来源/默认值 | 说明 |
|------|------|-------------|------|
| `index` | int | 递增计数器（起始值0，发布前自增） | 第一条消息index为1 |
| `timestamp` | int | `self.node.get_clock().now().nanoseconds` | 直接获取纳秒时间戳，避免float精度问题 |
| `text` | string | 输入参数 | 来自`~/asr_input`或API |
| `angle` | int | `90` | 固定默认值 |
| `speaker_id` | int | `0` | 固定默认值 |
| `sense` | string | `"unknown"` | 固定默认值 |
| `confidence` | float | `0.95` | 固定默认值 |
| `language` | string | `"zh-CN"` | 固定默认值 |
| `is_final` | bool | `true` | 固定默认值 |

### 5. play_state消息

**触发时机**:
- `start_play` API调用成功时 → 发布`{"play_state": 1}`
- `stop_play` API调用成功时 → 发布`{"play_state": 0}`

**发布位置**: 在`node.py`的`on_voice_request()`中，检查API响应成功后发布

**架构原则**: `model.py`负责状态和payload，`node.py`负责ROS副作用（发布消息）

---

## 实现要点

### 文件变更

**主要文件**: `src/g1_sim/g1_sim/node.py`
- 新增订阅: `~/asr_input`
- 新增回调: `_on_asr_input_callback()`
- 重构方法: `_publish_audio_msg()` → `publish_asr_message()`
- 新增方法: `publish_play_state()`

**状态文件**: `src/g1_sim/g1_sim/model.py`
- 新增字段: `asr_index: int` (初始值0，发布前自增，确保第一条消息index为1)

**配置文件**: `src/g1_sim/g1_sim/config.py`
- 新增topic映射: `"asr_input": "~/asr_input"`

### 关键代码结构

```python
class G1SimNode:
    def __init__(self, node, config: G1SimConfig):
        # ... 现有代码 ...
        
        # 新增订阅
        node.create_subscription(
            self.msg["String"], 
            topics["asr_input"], 
            self._on_asr_input_callback, 
            10
        )
    
    def _on_asr_input_callback(self, msg) -> None:
        """处理模拟麦克风输入"""
        text = getattr(msg, "data", "")
        if text:
            self.publish_asr_message(text)

    def publish_asr_message(self, text: str) -> None:
        """发布ASR消息（JSON格式）"""
        self.state.asr_index += 1  # 先自增，确保第一条消息index为1
        asr_json = {
            "index": self.state.asr_index,
            "timestamp": self.node.get_clock().now().nanoseconds,  # 直接获取纳秒时间戳
            "text": text,
            "angle": 90,
            "speaker_id": 0,
            "sense": "unknown",
            "confidence": 0.95,
            "language": "zh-CN",
            "is_final": True,
        }
        
        msg = self.msg["String"]()
        msg.data = json.dumps(asr_json, ensure_ascii=False)
        self.audio_msg_pub.publish(msg)
    
    def publish_play_state(self, is_playing: bool) -> None:
        """发布播放状态消息"""
        play_state_json = {"play_state": 1 if is_playing else 0}
        msg = self.msg["String"]()
        msg.data = json.dumps(play_state_json)
        self.audio_msg_pub.publish(msg)
```

### 集成点

**在`on_voice_request()`中**:

```python
def on_voice_request(self, msg) -> None:
    # 调用handle_voice_api获取响应
    code, payload = handle_voice_api(...)

    # 发布响应
    self.voice_response_pub.publish(response)

    # 根据API结果触发副作用
    if code == 0:  # API成功
        action = payload.get("action")
        if action == "asr":
            # 使用payload中的最终text（可能包含默认值处理）
            self.publish_asr_message(payload.get("text", ""))
        elif action == "start_play":
            self.publish_play_state(is_playing=True)
        elif action == "stop_play":
            self.publish_play_state(is_playing=False)
```

**设计原则**:
- 避免在`on_voice_request()`中重复解析request参数
- 统一使用`handle_voice_api()`的返回值
- 所有ROS副作用（发布消息）都在node.py中处理

---

## 边界情况处理

基于Codex审查建议，需要明确以下边界情况的行为：

### 1. 空字符串ASR输入
**行为**: 忽略空字符串，不发布ASR消息
```python
def _on_asr_input_callback(self, msg) -> None:
    text = getattr(msg, "data", "").strip()
    if text:  # 非空才发布
        self.publish_asr_message(text)
```

### 2. 重复调用start_play
**行为**: 每次调用都发布`{"play_state": 1}`，即使已经处于播放状态
**理由**: 保持简单和一致性，消费者负责处理重复的状态消息

### 3. 停止不存在的app
**行为**: API返回accepted，但stopped_streams为空，此时**不发布**play_state消息
```python
if action == "stop_play":
    stopped_streams = payload.get("stopped_streams", [])
    if stopped_streams:  # 只有实际停止了stream才发布
        self.publish_play_state(is_playing=False)
```

### 4. 多app播放时停止一个
**行为**: 简化处理，只要停止了任何stream就发布`{"play_state": 0}`
**理由**: 模拟器不需要复杂的播放状态追踪，保持简单

### 5. /audio_msg混合消息格式
**行为**: 同一个topic上会出现两种消息格式
- ASR消息: 包含`text`字段
- play_state消息: 只包含`play_state`字段

**消费者处理策略**:
```python
def on_audio_msg(msg):
    try:
        data = json.loads(msg.data)
        if "text" in data:
            # 处理ASR消息
            handle_asr(data)
        elif "play_state" in data:
            # 处理play_state消息
            handle_play_state(data)
        else:
            logger.warning(f"Unknown audio_msg format: {data}")
    except json.JSONDecodeError:
        # Fallback到旧版纯文本
        handle_legacy_text(msg.data)
```

---

## 架构和职责分离

### 核心原则
**model.py负责状态和业务逻辑，node.py负责ROS副作用**

- `handle_voice_api()`: 纯函数，处理API逻辑，返回payload
- `on_voice_request()`: 调用handle_voice_api，根据结果发布消息
- `publish_asr_message()`: node层方法，负责ROS发布
- `publish_play_state()`: node层方法，负责ROS发布

### 副作用统一处理
建议在node.py中添加统一的副作用处理方法：

```python
def _publish_voice_side_effects(self, code: int, payload: dict) -> None:
    """根据voice API结果发布副作用消息"""
    if code != 0:
        return  # API失败，不发布副作用

    action = payload.get("action")
    if action == "asr":
        self.publish_asr_message(payload.get("text", ""))
    elif action == "start_play":
        self.publish_play_state(is_playing=True)
    elif action == "stop_play" and payload.get("stopped_streams"):
        self.publish_play_state(is_playing=False)
```

---

## 测试场景

### 场景1：通过topic模拟麦克风输入
```bash
# 终端1：启动g1_sim
ros2 run g1_sim g1_sim_node

# 终端2：模拟麦克风输入
ros2 topic pub /g1_sim/asr_input std_msgs/msg/String "data: '你好世界'"

# 终端3：监听audio_msg
ros2 topic echo /audio_msg
# 期望输出：完整的ASR JSON
```

### 场景2：通过API触发ASR
```bash
# 发送asr API请求
ros2 topic pub /api/voice/request unitree_api/msg/Request "{...}"

# 监听audio_msg
ros2 topic echo /audio_msg
# 期望输出：完整的ASR JSON
```

### 场景3：play_state消息
```bash
# 发送start_play API
ros2 topic pub /api/voice/request ...

# 监听audio_msg
ros2 topic echo /audio_msg
# 期望输出：{"play_state": 1}

# 发送stop_play API
# 期望输出：{"play_state": 0}
```

---

## 兼容性说明

### 向后兼容性

**破坏性变更**: `/audio_msg`的消息格式从纯文本变为JSON字符串

**影响范围**:
- 所有订阅`/audio_msg`的消费者需要更新解析逻辑
- `voice_bridge`包需要相应修改

**迁移路径**:

1. **JSON解析**: 消费者先尝试`json.loads(msg.data)`
2. **消息类型判别**:
   ```python
   try:
       data = json.loads(msg.data)
       if "text" in data:
           # 处理ASR消息
           handle_asr_event(data["text"], data)
       elif "play_state" in data:
           # 处理play_state消息或忽略
           handle_play_state(data["play_state"])
       else:
           logger.warning(f"Unknown audio_msg format: {data}")
   except json.JSONDecodeError:
       # Fallback到旧版纯文本
       handle_legacy_asr_text(msg.data)
   ```
3. **过渡期**: 在日志中warning非JSON格式，帮助识别遗留消费者
4. **类型安全**: timestamp字段可能超过JavaScript Number安全范围，消费者应使用BigInt

**重要**: 同一个topic上会出现两种消息格式（ASR和play_state），消费者必须根据字段名判别消息类型，不能假设所有消息都是ASR。

### 与真实硬件的兼容性

**符合性**: 本设计完全符合Unitree G1官方文档定义的ASR消息格式

**差异点**:
- 真实硬件的ASR字段值由实际识别结果决定
- 模拟器使用固定默认值（angle、speaker_id等）
- 这是模拟器的合理简化，不影响集成测试

---

## 未来扩展

### 可能的增强

1. **高级ASR参数控制**: 新增`~/asr_input_json` topic，允许完整控制所有ASR字段
2. **动态字段值**: 根据测试场景动态生成angle、speaker_id等值
3. **ASR状态查询**: 通过service接口查询当前ASR配置和状态
4. **多语言支持**: 通过配置支持不同language默认值

### 扩展点识别

- `publish_asr_message()` 方法可以扩展为接受可选参数覆盖默认值
- `config.sim` 可以添加`asr_field_defaults`配置段
- 可以添加ASR相关的service接口

---

## 风险和缓解

### 风险1：JSON解析失败导致消费者崩溃

**缓解**: 消费者应使用try-catch包装JSON解析，fallback到纯文本

### 风险2：timestamp溢出

**现状**: timestamp为纳秒，可能超过JavaScript Number安全范围

**缓解**: 文档中明确timestamp为整数类型，消费者应使用BigInt或字符串解析

### 风险3：asr_index溢出

**现状**: 长期运行可能溢出（Python int无上限，但JSON序列化后可能有问题）

**缓解**: 可以在达到阈值时重置为0，或使用更大的类型

---

## 验收标准

### 功能验收

- [ ] `/audio_msg`发布的是完整JSON格式的ASR消息
- [ ] JSON包含所有9个必需字段
- [ ] index字段每次递增，第一条消息index为1
- [ ] timestamp字段直接使用nanoseconds（避免float精度问题）
- [ ] text字段来自输入参数
- [ ] 其他字段使用正确的默认值
- [ ] `~/asr_input`收到文本时触发ASR消息发布
- [ ] `asr` API调用时触发ASR消息发布（使用payload中的text）
- [ ] `start_play`/`stop_play`时发布play_state消息
- [ ] 空字符串输入被忽略，不发布消息
- [ ] 停止不存在的app时不发布play_state消息

### 测试验收

- [ ] 单元测试覆盖`publish_asr_message()`方法
- [ ] 单元测试覆盖`publish_play_state()`方法
- [ ] 单元测试验证timestamp为int类型
- [ ] 单元测试验证index连续递增
- [ ] 单元测试覆盖边界情况（空字符串、重复调用等）
- [ ] 集成测试验证完整消息流
- [ ] 集成测试验证`~/asr_input`到ASR消息的流程
- [ ] 集成测试验证ASR API到ASR消息的流程
- [ ] 集成测试验证play_state消息的发布时机
- [ ] 现有测试不破坏（除了需要适配JSON格式）
- [ ] voice_bridge能够解析新的JSON格式
- [ ] voice_bridge能够区分ASR和play_state消息

### 配置验收

- [ ] 默认配置包含`asr_input` topic映射
- [ ] YAML配置可以覆盖`asr_input` topic名称
- [ ] 验证逻辑检查`asr_input`配置存在

### 文档验收

- [ ] 设计文档完整且已提交
- [ ] 代码注释充分
- [ ] README更新使用示例
- [ ] 更新迁移指南，明确区分ASR和play_state消息

---

## 参考资料

- Unitree G1 ASR文档（用户提供）
- `docs/unitree_ros2_topics.md` - ROS2 topic参考
- `src/g1_sim/README.md` - 当前模拟器文档
- `docs/G1_H1_API_Documentation.md` - G1 API参考
