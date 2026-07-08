# ASR Audio Msg Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `g1_interface` 把 Unitree SDK2/native `/audio_msg` 上的 ASR 文本桥接到项目内部 `/g1/audio/asr`，使 `g1_sim` 和真机 ASR 能自动驱动 `voice_bridge`。

**Architecture:** `g1_interface` 是本仓库已有的 native ROS2 topic 到项目内部 topic 的桥接节点，因此在这里新增一个处理 `/audio_msg` 的轻量桥接边界。桥接层订阅 native `/audio_msg`，将所有消息分类为 ASR（有 `text` 字段的 JSON 或纯文本）和非 ASR（如播放状态），分别发布到 `/g1/audio/asr` 和 `/g1/audio/event`。ASR payload 原文发布到 `/g1/audio/asr`，由 `voice_bridge.parse_asr_event` 继续负责 ASR schema 解析和置信度校验；非 ASR 音频事件原样发布到 `/g1/audio/event`，供下游节点（如 debug panel、音频状态监控）消费。

**Tech Stack:** Python 3.10, ROS2 Humble, `std_msgs/msg/String`, pytest, nix develop shell.

## Global Constraints

- 所有验证命令必须在 `nix develop` 环境内运行。
- 设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，避免用户级 pytest 插件影响测试。
- 追加 `PYTHONPATH=src/<package>:${PYTHONPATH:-}`，不要覆盖 nix/ROS 注入的 Python path。
- 不改变 `voice_bridge` 的运动安全边界：`voice_bridge` 仍只发布 `/voice/cmd/*`，不直接发布 `/api/*` 或低层控制 topic。
- `/audio_msg` 上的非 ASR JSON（如 `{"play_state": 1}`）不能转发到 `/g1/audio/asr`，但必须桥接到 `/g1/audio/event`。
- ASR JSON 原文应尽量原样转发，避免 `g1_interface` 复制 `voice_bridge` 的 parser 逻辑。

---

## Root Cause Summary

代码检查确认：

- `voice_bridge` 订阅 `topics.asr`，默认 `/g1/audio/asr`。
- `g1_sim` 和 SDK2 native ASR 使用 `/audio_msg`。
- `g1_interface` 当前没有订阅 `/audio_msg`，也没有发布 `/g1/audio/asr`。
- `voice_bridge.parse_asr_event` 已能解析 `g1_sim.publish_asr_message()` 产生的 JSON 字段，额外字段会被忽略。

因此根因是 topic 桥接缺失，不是 ASR JSON schema 不兼容。

## File Structure

- Modify: `src/g1_interface/g1_interface/config.py`
  - 新增 `native_topics.audio_msg` 默认值。
  - 新增 `project_topics.asr` 默认值。
  - 新增 `project_topics.audio_event` 默认值。
  - 在 `G1InterfaceConfig` dataclass 中暴露 `project_topics`。
  - 校验 `audio_msg`、`project_topics.asr` 和 `project_topics.audio_event` 非空。
- Modify: `src/g1_interface/config/g1_interface.yaml`
  - 写入 `native_topics.audio_msg: /audio_msg`。
  - 写入 `project_topics.asr: /g1/audio/asr`。
  - 写入 `project_topics.audio_event: /g1/audio/event`。
- Modify: `src/g1_interface/g1_interface/node.py`
  - 新增纯函数 `normalize_audio_asr_message(raw_text: str) -> str | None`。
  - 新增 publisher `self.asr_pub` 发布到 `config.project_topics["asr"]`。
  - 新增 publisher `self.audio_event_pub` 发布到 `config.project_topics["audio_event"]`。
  - 新增 subscription 订阅 `config.native_topics["audio_msg"]`，callback 为 `on_audio_msg`。
  - `on_audio_msg` 将 ASR 消息转发到 `/g1/audio/asr`，非 ASR 消息转发到 `/g1/audio/event`。
- Modify: `src/g1_interface/tests/test_config.py`
  - 覆盖新增默认配置、YAML override、空 topic 校验。
- Modify: `src/g1_interface/tests/test_node_helpers.py`
  - 覆盖 ASR normalization 纯函数。
- Create: `src/g1_interface/tests/test_asr_bridge_node.py`
  - 用 fake ROS node 验证订阅和发布 wiring。
- Modify: `docs/data_contracts.md`
  - 在总体流向和音频契约中记录 `/audio_msg -> /g1/audio/asr`。
- Modify: `docs/g1_native_topic_sim.md`
  - 记录模拟器 `/audio_msg` 会经 `g1_interface` 桥接到 `/g1/audio/asr`。

---

### Task 1: Add Config Contract for Native Audio and Project ASR Topics

**Files:**
- Modify: `src/g1_interface/g1_interface/config.py`
- Modify: `src/g1_interface/config/g1_interface.yaml`
- Test: `src/g1_interface/tests/test_config.py`

**Interfaces:**
- Produces: `G1InterfaceConfig.project_topics: dict[str, str]`
- Produces: `config.native_topics["audio_msg"]`
- Produces: `config.project_topics["asr"]`
- Produces: `config.project_topics["audio_event"]`
- Consumes: existing `G1InterfaceConfig.from_yaml(path)` deep merge behavior

- [ ] **Step 1: Write the failing config tests**

Append these assertions to `test_default_config_uses_unitree_ros2_topic_names` in `src/g1_interface/tests/test_config.py`:

```python
    assert config.native_topics["audio_msg"] == "/audio_msg"
    assert config.project_topics["asr"] == "/g1/audio/asr"
    assert config.project_topics["audio_event"] == "/g1/audio/event"
```

Append this assertion to `test_yaml_overrides_defaults`:

```python
    assert config.project_topics["asr"] == "/g1/audio/asr"
    assert config.project_topics["audio_event"] == "/g1/audio/event"
```

Add this new test:

```python
def test_project_asr_topic_can_be_overridden(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
native_topics:
  audio_msg: /robot/audio_msg
project_topics:
  asr: /robot/g1/audio/asr
  audio_event: /robot/g1/audio/event
""",
        encoding="utf-8",
    )

    config = G1InterfaceConfig.from_yaml(config_path)

    assert config.native_topics["audio_msg"] == "/robot/audio_msg"
    assert config.project_topics["asr"] == "/robot/g1/audio/asr"
    assert config.project_topics["audio_event"] == "/robot/g1/audio/event"
```

Add this new validation test:

```python
def test_audio_bridge_topics_are_required(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
native_topics:
  audio_msg: ""
project_topics:
  asr: ""
  audio_event: ""
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing topic config: native_topics.audio_msg, project_topics.asr, project_topics.audio_event"):
        G1InterfaceConfig.from_yaml(config_path)
```

- [ ] **Step 2: Run the failing config tests**

Run:

```bash
nix develop --command bash -lc 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface:${PYTHONPATH:-} python -m pytest src/g1_interface/tests/test_config.py -q'
```

Expected before implementation: FAIL because `G1InterfaceConfig` has no `project_topics` field and no `audio_msg` default.

- [ ] **Step 3: Implement config defaults and validation**

In `src/g1_interface/g1_interface/config.py`, add `audio_msg` to `DEFAULT_CONFIG["native_topics"]`:

```python
        "audio_msg": "/audio_msg",
```

Add a new top-level config section after `native_topics`:

```python
    "project_topics": {
        "asr": "/g1/audio/asr",
        "audio_event": "/g1/audio/event",
    },
```

Change the dataclass from:

```python
@dataclass(frozen=True)
class G1InterfaceConfig:
    robot: dict[str, Any]
    native_topics: dict[str, str]
    control: dict[str, Any]
    timeouts: dict[str, int]
    sport_api: dict[str, Any]
```

to:

```python
@dataclass(frozen=True)
class G1InterfaceConfig:
    robot: dict[str, Any]
    native_topics: dict[str, str]
    project_topics: dict[str, str]
    control: dict[str, Any]
    timeouts: dict[str, int]
    sport_api: dict[str, Any]
```

Change `_from_dict` to include:

```python
            project_topics=dict(raw["project_topics"]),
```

between `native_topics` and `control`.

Replace the current `required_topics` validation block with:

```python
        required_topics = [
            ("native_topics", "low_state"),
            ("native_topics", "low_state_low_freq"),
            ("native_topics", "secondary_imu"),
            ("native_topics", "sport_request"),
            ("native_topics", "sport_response"),
            ("native_topics", "audio_msg"),
            ("project_topics", "asr"),
            ("project_topics", "audio_event"),
        ]
        missing_topics = []
        for section, key in required_topics:
            mapping = getattr(self, section)
            if not mapping.get(key):
                missing_topics.append(f"{section}.{key}")
        if missing_topics:
            raise ValueError(f"missing topic config: {', '.join(missing_topics)}")
```

Update `test_runtime_required_topics_are_rejected_when_empty` expected message from:

```python
    with pytest.raises(ValueError, match="missing native topic config: low_state_low_freq, secondary_imu"):
```

to:

```python
    with pytest.raises(ValueError, match="missing topic config: native_topics.low_state_low_freq, native_topics.secondary_imu"):
```

- [ ] **Step 4: Update checked-in YAML config**

In `src/g1_interface/config/g1_interface.yaml`, add under `native_topics`:

```yaml
  audio_msg: /audio_msg
```

Add a new top-level section after `native_topics`:

```yaml
project_topics:
  asr: /g1/audio/asr
  audio_event: /g1/audio/event
```

- [ ] **Step 5: Run config tests**

Run:

```bash
nix develop --command bash -lc 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface:${PYTHONPATH:-} python -m pytest src/g1_interface/tests/test_config.py -q'
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/g1_interface/g1_interface/config.py src/g1_interface/config/g1_interface.yaml src/g1_interface/tests/test_config.py
git commit -m "config: add ASR bridge topics"
```

---

### Task 2: Implement `/audio_msg` to `/g1/audio/asr` Bridge in `g1_interface`

**Files:**
- Modify: `src/g1_interface/g1_interface/node.py`
- Test: `src/g1_interface/tests/test_node_helpers.py`
- Create: `src/g1_interface/tests/test_asr_bridge_node.py`

**Interfaces:**
- Consumes: `G1InterfaceConfig.native_topics["audio_msg"]`
- Consumes: `G1InterfaceConfig.project_topics["asr"]`
- Consumes: `G1InterfaceConfig.project_topics["audio_event"]`
- Produces: `normalize_audio_asr_message(raw_text: str) -> str | None`
- Produces: `G1InterfaceNode.on_audio_msg(msg) -> None`

- [ ] **Step 1: Write failing helper tests**

In `src/g1_interface/tests/test_node_helpers.py`, add `normalize_audio_asr_message` to the import list:

```python
    normalize_audio_asr_message,
```

Add these tests:

```python
def test_normalize_audio_asr_message_forwards_plain_text():
    assert normalize_audio_asr_message("停止") == "停止"


def test_normalize_audio_asr_message_forwards_asr_json_unchanged():
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    assert normalize_audio_asr_message(raw) == raw


def test_normalize_audio_asr_message_filters_non_asr_audio_events():
    assert normalize_audio_asr_message("") is None
    assert normalize_audio_asr_message("   ") is None
    assert normalize_audio_asr_message('{"play_state":1}') is None
    assert normalize_audio_asr_message('{"text":"   ","confidence":0.95}') is None
    assert normalize_audio_asr_message("[1, 2, 3]") is None
```

- [ ] **Step 2: Run failing helper tests**

Run:

```bash
nix develop --command bash -lc 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface:${PYTHONPATH:-} python -m pytest src/g1_interface/tests/test_node_helpers.py -q'
```

Expected before implementation: FAIL because `normalize_audio_asr_message` does not exist.

- [ ] **Step 3: Implement the normalizer**

In `src/g1_interface/g1_interface/node.py`, add this function after `diagnostic_level_for_state`:

```python
def normalize_audio_asr_message(raw_text: str) -> str | None:
    text = raw_text.strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text

    if not isinstance(payload, dict):
        return None

    event_text = str(payload.get("text", "")).strip()
    if not event_text:
        return None

    return text
```

- [ ] **Step 4: Write failing node wiring tests**

Create `src/g1_interface/tests/test_asr_bridge_node.py`:

```python
from __future__ import annotations

from g1_interface.config import G1InterfaceConfig
from g1_interface.node import G1InterfaceNode


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class FakeClockTime:
    nanoseconds = 1_000_000_000


class FakeClock:
    def now(self):
        return FakeClockTime()


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)


class FakeNode:
    def __init__(self):
        self.publishers = {}
        self.subscriptions = []
        self.timers = []
        self.logger = FakeLogger()

    def create_publisher(self, msg_type, topic, qos):
        publisher = FakePublisher()
        self.publishers[topic] = publisher
        return publisher

    def create_subscription(self, msg_type, topic, callback, qos):
        self.subscriptions.append((topic, callback))
        return callback

    def create_timer(self, period, callback):
        self.timers.append((period, callback))
        return callback

    def get_clock(self):
        return FakeClock()

    def get_logger(self):
        return self.logger


def _string_msg(data: str):
    from std_msgs.msg import String

    msg = String()
    msg.data = data
    return msg


def test_g1_interface_wires_audio_msg_to_project_asr_and_event_topics():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())

    audio_subscriptions = [topic for topic, callback in node.subscriptions if callback == bridge.on_audio_msg]

    assert audio_subscriptions == ["/audio_msg"]
    assert "/g1/audio/asr" in node.publishers
    assert "/g1/audio/event" in node.publishers


def test_audio_msg_callback_forwards_asr_json_unchanged():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    bridge.on_audio_msg(_string_msg(raw))

    published = node.publishers["/g1/audio/asr"].messages
    assert [msg.data for msg in published] == [raw]
    assert node.publishers["/g1/audio/event"].messages == []


def test_audio_msg_callback_bridges_play_state_to_audio_event():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())

    bridge.on_audio_msg(_string_msg('{"play_state":1}'))

    assert node.publishers["/g1/audio/asr"].messages == []
    published = node.publishers["/g1/audio/event"].messages
    assert [msg.data for msg in published] == ['{"play_state":1}']


def test_audio_msg_callback_bridges_empty_json_to_audio_event():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())

    bridge.on_audio_msg(_string_msg("[1, 2, 3]"))

    assert node.publishers["/g1/audio/asr"].messages == []
    published = node.publishers["/g1/audio/event"].messages
    assert [msg.data for msg in published] == ["[1, 2, 3]"]
```

- [ ] **Step 5: Run failing node wiring tests**

Run:

```bash
nix develop --command bash -lc 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface:${PYTHONPATH:-} python -m pytest src/g1_interface/tests/test_asr_bridge_node.py -q'
```

Expected before implementation: FAIL because `G1InterfaceNode.on_audio_msg` and `/g1/audio/asr` publisher do not exist.

- [ ] **Step 6: Implement publisher, subscription, and callback**

In `G1InterfaceNode.__init__`, after `self.imu_pub` is created, add:

```python
        self.asr_pub = node.create_publisher(self.msg["String"], config.project_topics["asr"], 10)
        self.audio_event_pub = node.create_publisher(self.msg["String"], config.project_topics["audio_event"], 10)
```

After the sport response subscription and before safe command subscriptions, add:

```python
        node.create_subscription(
            self.msg["String"],
            config.native_topics["audio_msg"],
            self.on_audio_msg,
            10,
        )
```

Add this method before `on_safe_loco`:

```python
    def on_audio_msg(self, msg) -> None:
        raw = getattr(msg, "data", "").strip()
        if not raw:
            return

        normalized = normalize_audio_asr_message(raw)
        if normalized is not None:
            text = self.msg["String"]()
            text.data = normalized
            self.asr_pub.publish(text)
        else:
            text = self.msg["String"]()
            text.data = raw
            self.audio_event_pub.publish(text)
```

- [ ] **Step 7: Run ASR bridge tests**

Run:

```bash
nix develop --command bash -lc 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface:${PYTHONPATH:-} python -m pytest src/g1_interface/tests/test_node_helpers.py src/g1_interface/tests/test_asr_bridge_node.py -q'
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/g1_interface/g1_interface/node.py src/g1_interface/tests/test_node_helpers.py src/g1_interface/tests/test_asr_bridge_node.py
git commit -m "feat: bridge native ASR audio messages"
```

---

### Task 3: Document the ASR Bridge and Verify Package Boundary

**Files:**
- Modify: `docs/data_contracts.md`
- Modify: `docs/g1_native_topic_sim.md`

**Interfaces:**
- Consumes: `/audio_msg` native `std_msgs/msg/String`
- Produces: `/g1/audio/asr` project-internal `std_msgs/msg/String`
- Produces: `/g1/audio/event` project-internal `std_msgs/msg/String`

- [ ] **Step 1: Update `docs/data_contracts.md` flow**

In the "总体流向" code block, change the first `g1_interface` section from:

```text
g1_interface
  publishes /g1/state/low, /g1/state/mode, /g1/state/health
```

to:

```text
g1_interface
  subscribes /audio_msg
  publishes /g1/audio/asr, /g1/audio/event, /g1/state/low, /g1/state/mode, /g1/state/health
```

After the `/g1/state/health` section, add:

```markdown
### `/g1/audio/asr`

`std_msgs/msg/String`。`g1_interface` 从 native `/audio_msg` 转发 ASR 文本事件到该项目内部 topic。

允许两种输入形态：

- plain text，例如 `停止`
- JSON object，且 `text` 字段非空，例如：

```json
{
  "index": 1,
  "timestamp": 1000000000,
  "text": "宇树，向前走一秒",
  "confidence": 0.95,
  "is_final": true,
  "language": "zh-CN"
}
```

### `/g1/audio/event`

`std_msgs/msg/String`。`g1_interface` 从 native `/audio_msg` 转发非 ASR 音频事件到该项目内部 topic。

用于桥接非 ASR 的 `/audio_msg` 消息（如播放状态 `{"play_state": 1}`），供 debug panel、音频状态监控等下游节点消费。消息原样转发，不做 schema 解析。
```

- [ ] **Step 2: Update `docs/g1_native_topic_sim.md`**

Find the bullet that says:

```markdown
- Voice ASR returns a configurable text payload through `/api/voice/response` and publishes the same text on ROS2 `/audio_msg`, which maps to SDK2 DDS `rt/audio_msg`.
```

Replace it with:

```markdown
- Voice ASR returns a configurable text payload through `/api/voice/response` and publishes the same text on ROS2 `/audio_msg`, which maps to SDK2 DDS `rt/audio_msg`. `g1_interface` bridges ASR-shaped `/audio_msg` events into the project-internal `/g1/audio/asr` topic consumed by `voice_bridge`; non-ASR audio events such as play-state JSON are bridged to `/g1/audio/event` for downstream consumers.
```

- [ ] **Step 3: Run all relevant tests**

Run:

```bash
nix develop --command bash -lc 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface:${PYTHONPATH:-} python -m pytest src/g1_interface/tests -q'
```

Expected: PASS.

Run:

```bash
nix develop --command bash -lc 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/voice_bridge:${PYTHONPATH:-} python -m pytest src/voice_bridge/tests -q'
```

Expected: PASS.

Run:

```bash
nix develop --command bash -lc 'colcon build --symlink-install --packages-select g1_interface voice_bridge'
```

Expected: PASS.

- [ ] **Step 4: Optional ROS graph smoke test**

Run in terminal 1:

```bash
nix develop --command bash -lc 'source install/setup.bash 2>/dev/null || true; ros2 launch g1_interface g1_interface.launch.py config_path:=src/g1_interface/config/g1_interface.yaml'
```

Run in terminal 2 (ASR):

```bash
nix develop --command bash -lc 'source install/setup.bash 2>/dev/null || true; ros2 topic echo /g1/audio/asr std_msgs/msg/String'
```

Run in terminal 3 (audio event):

```bash
nix develop --command bash -lc 'source install/setup.bash 2>/dev/null || true; ros2 topic echo /g1/audio/event std_msgs/msg/String'
```

Run in terminal 4:

```bash
nix develop --command bash -lc 'source install/setup.bash 2>/dev/null || true; ros2 topic pub --once /audio_msg std_msgs/msg/String "{data: '\''{\"text\":\"宇树，向前走一秒\",\"confidence\":0.95,\"is_final\":true}'\''}"'
```

Expected terminal 2 output contains:

```text
data: '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true}'
```

Expected terminal 3: no message for the ASR event.

Run a play-state check:

```bash
nix develop --command bash -lc 'source install/setup.bash 2>/dev/null || true; ros2 topic pub --once /audio_msg std_msgs/msg/String "{data: '\''{\"play_state\":1}'\''}"'
```

Expected: terminal 2 receives no new `/g1/audio/asr` message. Terminal 3 output contains:

```text
data: '{"play_state":1}'
```

- [ ] **Step 5: Commit**

```bash
git add docs/data_contracts.md docs/g1_native_topic_sim.md
git commit -m "docs: document ASR audio bridge"
```

---

## Final Verification Checklist

- [ ] `nix develop --command bash -lc 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface:${PYTHONPATH:-} python -m pytest src/g1_interface/tests -q'` passes.
- [ ] `nix develop --command bash -lc 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/voice_bridge:${PYTHONPATH:-} python -m pytest src/voice_bridge/tests -q'` passes.
- [ ] `nix develop --command bash -lc 'colcon build --symlink-install --packages-select g1_interface voice_bridge'` passes.
- [ ] ROS graph smoke test confirms `/audio_msg` ASR JSON appears on `/g1/audio/asr` and not on `/g1/audio/event`.
- [ ] ROS graph smoke test confirms `/audio_msg` play-state JSON appears on `/g1/audio/event` and not on `/g1/audio/asr`.

## Self-Review Notes

- Spec coverage: covers the observed disconnect between `/audio_msg` and `/g1/audio/asr`, bridges non-ASR audio events to `/g1/audio/event` for downstream consumption, keeps parser ownership in `voice_bridge`, and documents the new contracts.
- Placeholder scan: no placeholder tasks remain.
- Type consistency: `project_topics` is introduced in config before `G1InterfaceNode` consumes it; `normalize_audio_asr_message` return type is used directly by `on_audio_msg`; `audio_event_pub` follows same pattern as `asr_pub`.
