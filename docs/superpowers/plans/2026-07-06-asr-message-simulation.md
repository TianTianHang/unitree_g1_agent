# ASR消息模拟修复实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复g1_sim模拟器中的ASR消息格式，使其符合Unitree G1官方文档定义的JSON格式，并添加play_state消息支持

**架构:** 在现有g1_sim架构基础上，添加~/asr_input订阅topic模拟麦克风输入，重构audio_msg发布逻辑以支持完整的JSON格式，保持model.py负责状态、node.py负责ROS副作用的职责分离

**Tech Stack:** ROS2 Humble, Python 3.11+, pytest, JSON, std_msgs

## Global Constraints

- **Python版本**: 3.11+
- **ROS2版本**: Humble
- **消息类型**: std_msgs/msg/String
- **JSON格式**: 必须包含ASR的9个字段（index, timestamp, text, angle, speaker_id, sense, confidence, language, is_final）
- **timestamp精度**: 直接使用nanoseconds，避免float精度问题
- **index起始值**: 第一条消息index为1（发布前自增）
- **职责分离**: model.py负责状态和业务逻辑，node.py负责ROS副作用
- **命名规范**: ~/asr_input使用私有命名空间，避免污染全局命名空间
- **测试优先**: 每个功能必须先编写测试

---

## 文件结构

**创建文件**: 无

**修改文件**:
- `src/g1_sim/g1_sim/model.py` - 添加asr_index字段到SimulatedRobotState
- `src/g1_sim/g1_sim/config.py` - 添加asr_input topic映射和验证
- `src/g1_sim/g1_sim/node.py` - 重构audio_msg发布逻辑，添加新订阅和回调
- `src/g1_sim/tests/test_model.py` - 测试asr_index字段
- `src/g1_sim/tests/test_config.py` - 测试asr_input配置
- `src/g1_sim/tests/test_node.py` - 测试新的发布逻辑和回调

---

### Task 1: 添加asr_index字段到SimulatedRobotState

**Files:**
- Modify: `src/g1_sim/g1_sim/model.py:67-102`
- Test: `src/g1_sim/tests/test_model.py`

**Interfaces:**
- Consumes: 无（新增字段）
- Produces: `SimulatedRobotState.asr_index: int` - ASR消息序号计数器

**目的**: 为ASR消息添加递增序号字段，第一条消息index为1

- [ ] **Step 1: 编写失败的测试**

在`src/g1_sim/tests/test_model.py`末尾添加：

```python
def test_simulated_robot_state_asr_index():
    """测试asr_index字段初始值和递增"""
    from g1_sim.model import SimulatedRobotState
    
    state = SimulatedRobotState()
    
    # 初始值应为0
    assert state.asr_index == 0
    
    # 模拟发布前自增
    state.asr_index += 1
    assert state.asr_index == 1
    
    # 第二次自增
    state.asr_index += 1
    assert state.asr_index == 2
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_model.py::test_simulated_robot_state_asr_index -v
```

Expected: FAIL - AttributeError: 'SimulatedRobotState' object has no attribute 'asr_index'

- [ ] **Step 3: 实现asr_index字段**

修改`src/g1_sim/g1_sim/model.py`的`SimulatedRobotState`类，在`playback_history`字段后添加：

```python
@dataclass
class SimulatedRobotState:
    motor_count: int = 35
    hand_motor_count: int = 7
    # ... 其他字段保持不变 ...
    playback_history: list[dict[str, Any]] = field(default_factory=list)
    asr_index: int = 0  # 添加这一行
```

- [ ] **Step 4: 运行测试验证通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_model.py::test_simulated_robot_state_asr_index -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/g1_sim/g1_sim/model.py src/g1_sim/tests/test_model.py
git commit -m "feat(g1_sim): add asr_index field to SimulatedRobotState

- Add asr_index counter starting at 0
- First ASR message will have index=1 (increment before publish)
- Add test to verify initial value and increment behavior"
```

---

### Task 2: 添加asr_input topic配置

**Files:**
- Modify: `src/g1_sim/g1_sim/config.py:29, 164`
- Test: `src/g1_sim/tests/test_config.py`

**Interfaces:**
- Consumes: 无（新增配置）
- Produces: `G1SimConfig.topics["asr_input"]` - asr_input topic名称

**目的**: 添加asr_input topic配置，支持通过YAML覆盖

- [ ] **Step 1: 编写失败的测试**

在`src/g1_sim/tests/test_config.py`末尾添加：

```python
def test_default_config_includes_asr_input():
    """测试默认配置包含asr_input topic"""
    from g1_sim.config import G1SimConfig
    
    config = G1SimConfig.default()
    
    assert "asr_input" in config.topics
    assert config.topics["asr_input"] == "~/asr_input"

def test_yaml_config_can_override_asr_input():
    """测试YAML配置可以覆盖asr_input topic"""
    from g1_sim.config import G1SimConfig
    import tempfile
    import os
    
    yaml_content = """
topics:
  asr_input: "/custom/asr_input"
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        yaml_path = f.name
    
    try:
        config = G1SimConfig.from_yaml(yaml_path)
        assert config.topics["asr_input"] == "/custom/asr_input"
    finally:
        os.unlink(yaml_path)
```

- [ ] **Step 2: 运行测试验证失败**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_config.py::test_default_config_includes_asr_input -v
```

Expected: FAIL - asr_input不在topics中或值不匹配

- [ ] **Step 3: 添加默认配置**

修改`src/g1_sim/g1_sim/config.py`，在DEFAULT_CONFIG的topics字典中，`"audio_msg"`行后添加：

```python
"topics": {
    # ... 现有topics ...
    "audio_msg": "/audio_msg",
    "asr_input": "~/asr_input",  # 添加这一行
    "sport_request": "/api/sport/request",
    # ... 其他topics ...
}
```

- [ ] **Step 4: 添加到required_topics列表**

修改`src/g1_sim/g1_sim/config.py`的`validate()`方法，在`"audio_msg"`后添加：

```python
def validate(self) -> None:
    required_topics = [
        # ... 现有topics ...
        "audio_msg",
        "asr_input",  # 添加这一行
        "sport_request",
        # ... 其他topics ...
    ]
    # ... 其余验证逻辑保持不变 ...
```

- [ ] **Step 5: 运行测试验证通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_config.py::test_default_config_includes_asr_input src/g1_sim/tests/test_config.py::test_yaml_config_can_override_asr_input -v
```

Expected: PASS

- [ ] **Step 6: 验证所有config测试仍然通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_config.py -v
```

Expected: 所有测试通过

- [ ] **Step 7: 提交**

```bash
git add src/g1_sim/g1_sim/config.py src/g1_sim/tests/test_config.py
git commit -m "feat(g1_sim): add asr_input topic configuration

- Add ~/asr_input to default topics configuration
- Add asr_input to required_topics validation
- Support YAML override for custom topic names
- Add tests for default and override scenarios"
```

---

### Task 3: 实现publish_asr_message方法

**Files:**
- Modify: `src/g1_sim/g1_sim/node.py:260-263`
- Test: `src/g1_sim/tests/test_node.py`

**Interfaces:**
- Consumes: `self.state.asr_index`, `self.node.get_clock()`, `self.audio_msg_pub`
- Produces: `G1SimNode.publish_asr_message(text: str) -> None` - 发布ASR JSON消息

**目的**: 重构audio_msg发布逻辑，从纯文本改为完整的JSON格式

- [ ] **Step 1: 编写失败的测试**

在`src/g1_sim/tests/test_node.py`末尾添加：

```python
def test_publish_asr_message_json_format(monkeypatch):
    """测试publish_asr_message发布完整JSON格式"""
    import json
    from unittest.mock import MagicMock
    from g1_sim.config import G1SimConfig
    from g1_sim.node import G1SimNode
    import rclpy
    
    # Mock ROS2 node
    mock_node = MagicMock()
    mock_clock = MagicMock()
    mock_clock.now.return_value.nanoseconds = 12345678900000000
    mock_node.get_clock.return_value = mock_clock
    mock_node.create_publisher.return_value = MagicMock()
    mock_node.create_subscription = MagicMock()
    
    config = G1SimConfig.default()
    node = G1SimNode(mock_node, config)
    
    # Mock publisher to capture messages
    published_messages = []
    def capture_message(msg):
        published_messages.append(msg.data)
    node.audio_msg_pub.publish = capture_message
    
    # Publish ASR message
    node.publish_asr_message("测试文本")
    
    # Verify
    assert len(published_messages) == 1
    msg_data = json.loads(published_messages[0])
    
    # Check all required fields
    assert msg_data["index"] == 1
    assert msg_data["timestamp"] == 12345678900000000
    assert msg_data["text"] == "测试文本"
    assert msg_data["angle"] == 90
    assert msg_data["speaker_id"] == 0
    assert msg_data["sense"] == "unknown"
    assert msg_data["confidence"] == 0.95
    assert msg_data["language"] == "zh-CN"
    assert msg_data["is_final"] == True
    
    # Check index increment
    assert node.state.asr_index == 1
    
    # Second message should have index=2
    node.publish_asr_message("第二文本")
    assert len(published_messages) == 2
    msg_data2 = json.loads(published_messages[1])
    assert msg_data2["index"] == 2

def test_publish_asr_message_timestamp_is_int(monkeypatch):
    """测试timestamp字段为整数类型"""
    import json
    from unittest.mock import MagicMock
    from g1_sim.config import G1SimConfig
    from g1_sim.node import G1SimNode
    
    mock_node = MagicMock()
    mock_clock = MagicMock()
    mock_clock.now.return_value.nanoseconds = 12345678900000000
    mock_node.get_clock.return_value = mock_clock
    mock_node.create_publisher.return_value = MagicMock()
    mock_node.create_subscription = MagicMock()
    
    config = G1SimConfig.default()
    node = G1SimNode(mock_node, config)
    
    published_messages = []
    node.audio_msg_pub.publish = lambda msg: published_messages.append(msg.data)
    
    node.publish_asr_message("测试")
    
    msg_data = json.loads(published_messages[0])
    assert isinstance(msg_data["timestamp"], int)
    assert not isinstance(msg_data["timestamp"], float)
```

- [ ] **Step 2: 运行测试验证失败**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_publish_asr_message_json_format -v
```

Expected: FAIL - publish_asr_message方法不存在或逻辑不正确

- [ ] **Step 3: 实现publish_asr_message方法**

修改`src/g1_sim/g1_sim/node.py`，替换现有的`_publish_audio_msg`方法：

```python
import json  # 确保文件顶部有这个导入

def publish_asr_message(self, text: str) -> None:
    """发布ASR消息（JSON格式）
    
    发布符合Unitree G1官方文档格式的ASR消息，包含9个必需字段。
    index在发布前自增，确保第一条消息index为1。
    timestamp直接使用nanoseconds，避免float精度问题。
    
    Args:
        text: ASR识别的文本内容
    """
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
```

- [ ] **Step 4: 删除旧的_publish_audio_msg方法**

删除`src/g1_sim/g1_sim/node.py`中的旧方法：
```python
def _publish_audio_msg(self, text: str) -> None:
    msg = self.msg["String"]()
    msg.data = text
    self.audio_msg_pub.publish(msg)
```

- [ ] **Step 5: 运行测试验证通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_publish_asr_message_json_format src/g1_sim/tests/test_node.py::test_publish_asr_message_timestamp_is_int -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add src/g1_sim/g1_sim/node.py src/g1_sim/tests/test_node.py
git commit -m "feat(g1_sim): implement publish_asr_message with JSON format

- Replace plain text with complete JSON format (9 fields)
- Use nanoseconds directly for timestamp (avoid float precision)
- Increment index before publish (first message has index=1)
- Add comprehensive tests for JSON structure and types
- Remove old _publish_audio_msg method"
```

---

### Task 4: 实现publish_play_state方法

**Files:**
- Modify: `src/g1_sim/g1_sim/node.py` (在publish_asr_message后添加)
- Test: `src/g1_sim/tests/test_node.py`

**Interfaces:**
- Consumes: `self.audio_msg_pub`
- Produces: `G1SimNode.publish_play_state(is_playing: bool) -> None` - 发布播放状态消息

**目的**: 实现play_state消息发布，支持播放状态变化的副作用

- [ ] **Step 1: 编写失败的测试**

在`src/g1_sim/tests/test_node.py`末尾添加：

```python
def test_publish_play_state_format(monkeypatch):
    """测试publish_play_state发布正确格式"""
    import json
    from unittest.mock import MagicMock
    from g1_sim.config import G1SimConfig
    from g1_sim.node import G1SimNode
    
    mock_node = MagicMock()
    mock_node.create_publisher.return_value = MagicMock()
    mock_node.create_subscription = MagicMock()
    
    config = G1SimConfig.default()
    node = G1SimNode(mock_node, config)
    
    published_messages = []
    node.audio_msg_pub.publish = lambda msg: published_messages.append(msg.data)
    
    # Test playing state
    node.publish_play_state(True)
    assert len(published_messages) == 1
    msg_data = json.loads(published_messages[0])
    assert msg_data == {"play_state": 1}
    
    # Test stopped state
    node.publish_play_state(False)
    assert len(published_messages) == 2
    msg_data2 = json.loads(published_messages[1])
    assert msg_data2 == {"play_state": 0}
```

- [ ] **Step 2: 运行测试验证失败**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_publish_play_state_format -v
```

Expected: FAIL - publish_play_state方法不存在

- [ ] **Step 3: 实现publish_play_state方法**

在`src/g1_sim/g1_sim/node.py`的`publish_asr_message`方法后添加：

```python
def publish_play_state(self, is_playing: bool) -> None:
    """发布播放状态消息
    
    当语音播放状态发生变化时发布play_state消息。
    
    Args:
        is_playing: True表示开始播放，False表示停止播放
    """
    play_state_json = {"play_state": 1 if is_playing else 0}
    
    msg = self.msg["String"]()
    msg.data = json.dumps(play_state_json)
    self.audio_msg_pub.publish(msg)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_publish_play_state_format -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/g1_sim/g1_sim/node.py src/g1_sim/tests/test_node.py
git commit -m "feat(g1_sim): implement publish_play_state method

- Add play_state message publishing
- Format: {\"play_state\": 1} for playing, {\"play_state\": 0} for stopped
- Add test for both playing and stopped states"
```

---

### Task 5: 实现_on_asr_input_callback回调

**Files:**
- Modify: `src/g1_sim/g1_sim/node.py` (在publish_play_state后添加)
- Test: `src/g1_sim/tests/test_node.py`

**Interfaces:**
- Consumes: `self.publish_asr_message()`
- Produces: `G1SimNode._on_asr_input_callback(msg) -> None` - 处理模拟麦克风输入

**目的**: 实现asr_input topic的回调，处理模拟麦克风输入，忽略空字符串

- [ ] **Step 1: 编写失败的测试**

在`src/g1_sim/tests/test_node.py`末尾添加：

```python
def test_on_asr_input_callback_non_empty_text(monkeypatch):
    """测试非空文本触发ASR消息发布"""
    from unittest.mock import MagicMock
    from g1_sim.config import G1SimConfig
    from g1_sim.node import G1SimNode
    from std_msgs.msg import String
    
    mock_node = MagicMock()
    mock_node.create_publisher.return_value = MagicMock()
    mock_node.create_subscription = MagicMock()
    
    config = G1SimConfig.default()
    node = G1SimNode(mock_node, config)
    
    # Mock publish_asr_message to track calls
    asr_texts = []
    node.publish_asr_message = lambda text: asr_texts.append(text)
    
    # Test with non-empty text
    msg = String()
    msg.data = "测试语音"
    node._on_asr_input_callback(msg)
    
    assert len(asr_texts) == 1
    assert asr_texts[0] == "测试语音"

def test_on_asr_input_callback_empty_text_ignored(monkeypatch):
    """测试空文本被忽略"""
    from unittest.mock import MagicMock
    from g1_sim.config import G1SimConfig
    from g1_sim.node import G1SimNode
    from std_msgs.msg import String
    
    mock_node = MagicMock()
    mock_node.create_publisher.return_value = MagicMock()
    mock_node.create_subscription = MagicMock()
    
    config = G1SimConfig.default()
    node = G1SimNode(mock_node, config)
    
    asr_texts = []
    node.publish_asr_message = lambda text: asr_texts.append(text)
    
    # Test with empty text
    msg = String()
    msg.data = ""
    node._on_asr_input_callback(msg)
    
    assert len(asr_texts) == 0
    
    # Test with whitespace only
    msg.data = "   "
    node._on_asr_input_callback(msg)
    
    assert len(asr_texts) == 0
```

- [ ] **Step 2: 运行测试验证失败**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_on_asr_input_callback_non_empty_text -v
```

Expected: FAIL - _on_asr_input_callback方法不存在

- [ ] **Step 3: 实现_on_asr_input_callback方法**

在`src/g1_sim/g1_sim/node.py`的`publish_play_state`方法后添加：

```python
def _on_asr_input_callback(self, msg) -> None:
    """处理模拟麦克风输入
    
    当~/asr_input topic收到文本时，包装成ASR JSON消息发布。
    忽略空字符串和纯空白字符串。
    
    Args:
        msg: std_msgs/msg/String消息
    """
    text = getattr(msg, "data", "").strip()
    if text:  # 非空才发布
        self.publish_asr_message(text)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_on_asr_input_callback_non_empty_text src/g1_sim/tests/test_node.py::test_on_asr_input_callback_empty_text_ignored -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/g1_sim/g1_sim/node.py src/g1_sim/tests/test_node.py
git commit -m "feat(g1_sim): implement _on_asr_input_callback for asr_input

- Add callback to process simulated microphone input
- Ignore empty strings and whitespace-only input
- Trigger ASR message publishing on valid text
- Add tests for non-empty and empty text scenarios"
```

---

### Task 6: 在__init__中添加asr_input订阅

**Files:**
- Modify: `src/g1_sim/g1_sim/node.py:42-95`
- Test: `src/g1_sim/tests/test_node.py`

**Interfaces:**
- Consumes: `config.topics["asr_input"]`
- Produces: 订阅asr_input topic，连接到_on_asr_input_callback

**目的**: 在节点初始化时创建asr_input topic订阅

- [ ] **Step 1: 编写失败的测试**

在`src/g1_sim/tests/test_node.py`末尾添加：

```python
def test_init_creates_asr_input_subscription(monkeypatch):
    """测试__init__创建asr_input订阅"""
    from unittest.mock import MagicMock, call
    from g1_sim.config import G1SimConfig
    from g1_sim.node import G1SimNode
    
    mock_node = MagicMock()
    mock_publisher = MagicMock()
    mock_node.create_publisher.return_value = mock_publisher
    mock_node.create_subscription = MagicMock()
    
    config = G1SimConfig.default()
    G1SimNode(mock_node, config)
    
    # Verify create_subscription was called for asr_input
    subscription_calls = [c for c in mock_node.create_subscription.call_args_list 
                         if len(c[0]) > 1 and c[0][1] == config.topics["asr_input"]]
    
    assert len(subscription_calls) == 1
    
    # Verify callback is _on_asr_input_callback
    # The callback is the 3rd positional argument (index 2)
    callback_arg = subscription_calls[0][0][2]
    assert callback_arg.__name__ == "_on_asr_input_callback"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_init_creates_asr_input_subscription -v
```

Expected: FAIL - asr_input订阅不存在或回调不正确

- [ ] **Step 3: 在__init__中添加订阅**

修改`src/g1_sim/g1_sim/node.py`，在`self.audio_msg_pub = ...`行后添加：

```python
def __init__(self, node, config: G1SimConfig):
    self.node = node
    self.config = config
    self.msg = _load_ros_messages()
    self.state = SimulatedRobotState(
        motor_count=int(config.sim["motor_count"]),
        hand_motor_count=int(config.sim["hand_motor_count"]),
    )

    topics = config.topics
    self.low_state_pubs = [
        node.create_publisher(self.msg["LowState"], topics["low_state"], 10),
    ]
    # ... 其他publisher保持不变 ...
    self.audio_msg_pub = node.create_publisher(self.msg["String"], topics["audio_msg"], 10)
    
    # 添加asr_input订阅 - 在audio_msg_pub之后添加
    node.create_subscription(
        self.msg["String"], 
        topics["asr_input"], 
        self._on_asr_input_callback, 
        10
    )
    
    # ... 其余订阅保持不变 ...
    self.sport_response_pub = node.create_publisher(self.msg["Response"], topics["sport_response"], 10)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_init_creates_asr_input_subscription -v
```

Expected: PASS

- [ ] **Step 5: 验证所有现有node测试仍然通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py -v
```

Expected: 所有测试通过

- [ ] **Step 6: 提交**

```bash
git add src/g1_sim/g1_sim/node.py src/g1_sim/tests/test_node.py
git commit -m "feat(g1_sim): add asr_input topic subscription in __init__

- Create subscription for ~/asr_input topic
- Connect to _on_asr_input_callback for processing
- Add test to verify subscription creation
- All existing tests still pass"
```

---

### Task 7: 修改on_voice_request集成副作用发布

**Files:**
- Modify: `src/g1_sim/g1_sim/node.py:143-164`
- Test: `src/g1_sim/tests/test_node.py`

**Interfaces:**
- Consumes: `handle_voice_api()`, `self.publish_asr_message()`, `self.publish_play_state()`
- Produces: 修改后的on_voice_request，在API成功后发布副作用

**目的**: 集成ASR和play_state的副作用发布，避免重复解析request

- [ ] **Step 1: 编写失败的测试**

在`src/g1_sim/tests/test_node.py`末尾添加：

```python
def test_on_voice_request_publishes_asr_on_success(monkeypatch):
    """测试asr API成功时发布ASR消息"""
    import json
    from unittest.mock import MagicMock, patch
    from g1_sim.config import G1SimConfig
    from g1_sim.node import G1SimNode
    from unitree_api.msg import Request, Response
    
    mock_node = MagicMock()
    mock_publisher = MagicMock()
    mock_node.create_publisher.return_value = mock_publisher
    mock_node.create_subscription = MagicMock()
    mock_clock = MagicMock()
    mock_clock.now.return_value.nanoseconds = 12345678900000000
    mock_node.get_clock.return_value = mock_clock
    
    config = G1SimConfig.default()
    node = G1SimNode(mock_node, config)
    
    # Track published messages
    published_responses = []
    node.voice_response_pub.publish = lambda msg: published_responses.append(("response", msg))
    
    published_asr = []
    original_publish = node.publish_asr_message
    node.publish_asr_message = lambda text: published_asr.append(text)
    
    # Create ASR request
    req = Request()
    req.header.identity.id = 1
    req.header.identity.api_id = config.sim["voice_api_ids"]["asr"]
    req.parameter = json.dumps({"text": "API测试文本"})
    
    # Call on_voice_request
    node.on_voice_request(req)
    
    # Verify ASR was published
    assert len(published_asr) == 1
    assert published_asr[0] == "API测试文本"
    
    # Verify response was also published
    assert len(published_responses) == 1

def test_on_voice_request_publishes_play_state_on_start_play(monkeypatch):
    """测试start_play API成功时发布play_state=1"""
    from unittest.mock import MagicMock
    from g1_sim.config import G1SimConfig
    from g1_sim.node import G1SimNode
    from unitree_api.msg import Request
    import json
    
    mock_node = MagicMock()
    mock_node.create_publisher.return_value = MagicMock()
    mock_node.create_subscription = MagicMock()
    
    config = G1SimConfig.default()
    node = G1SimNode(mock_node, config)
    
    published_play_states = []
    node.publish_play_state = lambda is_playing: published_play_states.append(is_playing)
    
    # Create start_play request
    req = Request()
    req.header.identity.id = 1
    req.header.identity.api_id = config.sim["voice_api_ids"]["start_play"]
    req.parameter = json.dumps({"app_name": "test_app", "stream_id": "stream123"})
    
    node.on_voice_request(req)
    
    # Verify play_state was published
    assert len(published_play_states) == 1
    assert published_play_states[0] == True  # is_playing=True

def test_on_voice_request_no_play_state_on_failed_stop(monkeypatch):
    """测试停止不存在的app时不发布play_state"""
    from unittest.mock import MagicMock
    from g1_sim.config import G1SimConfig
    from g1_sim.node import G1SimNode
    from unitree_api.msg import Request
    import json
    
    mock_node = MagicMock()
    mock_node.create_publisher.return_value = MagicMock()
    mock_node.create_subscription = MagicMock()
    
    config = G1SimConfig.default()
    node = G1SimNode(mock_node, config)
    
    published_play_states = []
    node.publish_play_state = lambda is_playing: published_play_states.append(is_playing)
    
    # Create stop_play request for non-existent app
    req = Request()
    req.header.identity.id = 1
    req.header.identity.api_id = config.sim["voice_api_ids"]["stop_play"]
    req.parameter = json.dumps({"app_name": "non_existent_app"})
    
    node.on_voice_request(req)
    
    # Verify play_state was NOT published (no stream stopped)
    assert len(published_play_states) == 0
```

- [ ] **Step 2: 运行测试验证失败**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_on_voice_request_publishes_asr_on_success -v
```

Expected: FAIL - ASR消息未发布或逻辑不正确

- [ ] **Step 3: 修改on_voice_request方法**

修改`src/g1_sim/g1_sim/node.py`的`on_voice_request`方法：

```python
def on_voice_request(self, msg) -> None:
    """处理voice API请求，成功时发布副作用消息"""
    sequence_id, api_id = request_identity(msg)
    
    try:
        params = decode_request_parameter(msg)
        code, payload = handle_voice_api(
            self.state,
            api_id,
            params,
            self.config.sim["voice_api_ids"],
            str(self.config.sim["default_asr_text"]),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        code = 1
        payload = {"accepted": False, "service": "voice", "error": str(exc)}
        self.node.get_logger().warning(
            f"rejecting voice request sequence_id={sequence_id} api_id={api_id}: {exc}"
        )

    payload.setdefault("service", "voice")
    
    # 发布API响应
    self.voice_response_pub.publish(self._build_response(msg, code=code, payload=payload))
    
    # 根据API结果发布副作用消息
    if code == 0:  # API成功
        action = payload.get("action")
        if action == "asr":
            # 使用payload中的最终text（可能包含默认值处理）
            self.publish_asr_message(payload.get("text", ""))
        elif action == "start_play":
            self.publish_play_state(is_playing=True)
        elif action == "stop_play" and payload.get("stopped_streams"):
            # 只有实际停止了stream才发布play_state
            self.publish_play_state(is_playing=False)
```

**注意**: 删除原有的ASR特殊处理逻辑（第156-163行），现在统一通过副作用处理。

- [ ] **Step 4: 运行测试验证通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py::test_on_voice_request_publishes_asr_on_success src/g1_sim/tests/test_node.py::test_on_voice_request_publishes_play_state_on_start_play src/g1_sim/tests/test_node.py::test_on_voice_request_no_play_state_on_failed_stop -v
```

Expected: PASS

- [ ] **Step 5: 验证所有现有node测试仍然通过**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py -v
```

Expected: 所有测试通过

- [ ] **Step 6: 提交**

```bash
git add src/g1_sim/g1_sim/node.py src/g1_sim/tests/test_node.py
git commit -m "feat(g1_sim): integrate side-effect publishing in on_voice_request

- Publish ASR messages on successful asr API calls
- Publish play_state=1 on successful start_play
- Publish play_state=0 only when streams actually stopped
- Remove duplicate ASR handling logic
- Add tests for side-effect publishing scenarios
- All existing tests still pass"
```

---

### Task 8: 更新README文档

**Files:**
- Modify: `src/g1_sim/README.md`

**Interfaces:**
- Consumes: 设计文档
- Produces: 更新的README，包含ASR模拟使用说明

**目的**: 更新g1_sim的README，添加新的ASR模拟功能使用说明

- [ ] **Step 1: 读取当前README内容**

```bash
cat src/g1_sim/README.md
```

- [ ] **Step 2: 添加ASR模拟使用说明**

在`src/g1_sim/README.md`中找到合适的位置（通常在Usage或Examples章节），添加以下内容：

```markdown
## ASR消息模拟

g1_sim支持通过两种方式触发ASR消息发布：

### 方式1: 通过~/asr_input topic（推荐）

模拟麦克风输入，发布文本到asr_input topic：

```bash
# 启动g1_sim
ros2 run g1_sim g1_sim_node

# 在另一个终端，模拟麦克风输入
ros2 topic pub /g1_sim_node/asr_input std_msgs/msg/String "data: '你好世界'"

# 监听audio_msg查看ASR消息
ros2 topic echo /audio_msg
```

ASR消息格式（符合Unitree G1官方文档）：
```json
{
  "index": 1,
  "timestamp": 12345678900000000,
  "text": "你好世界",
  "angle": 90,
  "speaker_id": 0,
  "sense": "unknown",
  "confidence": 0.95,
  "language": "zh-CN",
  "is_final": true
}
```

### 方式2: 通过asr API调用

```bash
# 发送asr API请求
ros2 topic pub /api/voice/request unitree_api/msg/Request "{...}"
```

### play_state消息

当播放状态变化时，g1_sim会自动发布play_state消息：

```bash
# 监听audio_msg查看混合消息
ros2 topic echo /audio_msg
```

你会看到两种消息格式：
- ASR消息：包含`text`字段
- play_state消息：只包含`play_state`字段

### 消息格式迁移

从旧版纯文本迁移到新版JSON格式：
1. 尝试JSON解析`msg.data`
2. 如果有`text`字段，按ASR消息处理
3. 如果有`play_state`字段，按播放状态处理
4. 如果JSON解析失败，fallback到纯文本处理
```

- [ ] **Step 3: 提交**

```bash
git add src/g1_sim/README.md
git commit -m "docs(g1_sim): update README with ASR simulation usage

- Add ASR message simulation documentation
- Document ~/asr_input topic usage
- Document asr API usage
- Document play_state message format
- Add migration guide for JSON format change
- Include example commands and expected outputs"
```

---

## 验收总结

实现完成后，运行以下命令验证所有功能：

```bash
# 运行所有g1_sim测试
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests -v

# 验证配置
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_config.py -v

# 验证模型
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_model.py -v

# 验证节点逻辑
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests/test_node.py -v
```

所有测试应该通过，并且：
- ✅ ASR消息包含9个字段
- ✅ index从1开始递增
- ✅ timestamp为整数类型
- ✅ play_state消息在正确时机发布
- ✅ 空字符串输入被忽略
- ✅ 停止不存在的app时不发布play_state

---

## 设计文档参考

完整的设计文档参见：`docs/superpowers/specs/2025-01-06-asr-message-simulation-design.md`
