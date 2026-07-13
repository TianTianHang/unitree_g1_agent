# P0 Motion Watchdog and Sport Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `g1_interface` 增加独立于固件 `duration` 的本地运动看门狗，并把 Sport API、模式与 safety_control 心跳新鲜度纳入健康状态和运动准入。

**Architecture:** 保留 ROS 时钟用于对外状态消息时间戳，所有 deadline、请求超时和新鲜度判断统一改用 `time.monotonic()`；watchdog timer 使用 ROS 2 `STEADY_TIME`。状态和策略继续集中在 `G1InterfaceNode`，纯计算通过辅助函数测试；Sport API sequence ID 用于追踪最近一次速度命令确认，并在 deadline、心跳丢失、lowstate 丢失或运动命令未确认时幂等发布零速度。

**Tech Stack:** Python 3.10、ROS 2 Humble `rclpy`、`diagnostic_msgs`、`std_msgs`、pytest。

## Global Constraints

- 固件 `duration` 必须继续保留，本地 watchdog 是第二道独立停止机制。
- 所有安全 deadline 和 freshness 必须使用单调时钟，不能依赖 ROS/system time。
- `/g1/state/safety` 每 500 ms 发布一次，默认 1200 ms 未收到即视为心跳丢失。
- stop、watchdog stop 和 shutdown stop 不得被 lowstate、mode 或 heartbeat 门控阻止。
- `unhealthy` 必须映射为 ROS DiagnosticStatus ERROR（字节值 `b"\x02"`）。
- 不新增第三方 Python 依赖，不改变现有 ROS 消息类型和 Sport API JSON 编码。

---

### Task 1: 配置 safety 心跳与 watchdog 超时

**Files:**
- Modify: `src/g1_interface/g1_interface/config.py:37-68,129-178`
- Modify: `src/g1_interface/config/g1_interface.yaml:25-46`
- Test: `src/g1_interface/tests/test_config.py`

**Interfaces:**
- Consumes: 现有 `G1InterfaceConfig.default()`、`from_yaml()` 深合并和校验。
- Produces: `project_topics["safety_state"]`、`timeouts["motion_watchdog_period_ms"]`、`timeouts["safety_heartbeat_timeout_ms"]`、`timeouts["mode_freshness_timeout_ms"]`、`timeouts["api_unhealthy_timeout_count"]`。

- [x] **Step 1: 写配置失败测试**

```python
def test_default_watchdog_and_health_config():
    config = G1InterfaceConfig.default()
    assert config.project_topics["safety_state"] == "/g1/state/safety"
    assert config.timeouts["motion_watchdog_period_ms"] == 50
    assert config.timeouts["safety_heartbeat_timeout_ms"] == 1200
    assert config.timeouts["mode_freshness_timeout_ms"] == 1500
    assert config.timeouts["api_unhealthy_timeout_count"] == 3


def test_watchdog_timeouts_must_be_positive(tmp_path):
    path = tmp_path / "g1_interface.yaml"
    path.write_text("timeouts:\n  motion_watchdog_period_ms: 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="motion_watchdog_period_ms must be positive"):
        G1InterfaceConfig.from_yaml(path)
```

- [x] **Step 2: 运行配置测试并确认失败**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests/test_config.py`
Expected: FAIL，缺少新 topic/timeout，且零值尚未被拒绝。

- [x] **Step 3: 实现默认配置和严格校验**

```python
"project_topics": {
    "asr": "/g1/audio/asr",
    "audio_event": "/g1/audio/event",
    "safety_state": "/g1/state/safety",
},
"timeouts": {
    "state_timeout_ms": 300,
    "api_response_timeout_ms": 500,
    "health_publish_period_ms": 200,
    "mode_query_period_ms": 500,
    "motion_watchdog_period_ms": 50,
    "safety_heartbeat_timeout_ms": 1200,
    "mode_freshness_timeout_ms": 1500,
    "api_unhealthy_timeout_count": 3,
},
```

校验每个 timeout 都是非 bool 数值且大于零；`api_unhealthy_timeout_count` 额外要求为整数。将 `project_topics.safety_state` 加入 required topics。

- [x] **Step 4: 运行配置测试并确认通过**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests/test_config.py`
Expected: PASS。

---

### Task 2: 扩展纯健康状态和运动准入策略

**Files:**
- Modify: `src/g1_interface/g1_interface/node.py:75-99,189-202`
- Test: `src/g1_interface/tests/test_node_helpers.py`

**Interfaces:**
- Consumes: 单调秒值、各 freshness timeout、API timeout 计数和命令确认字典。
- Produces: `build_health_status(...) -> dict[str, Any]`、扩展后的 `check_sport_command_allowed(...) -> tuple[bool, str | None]`、三态 `diagnostic_level_for_state()`。

- [x] **Step 1: 写健康策略失败测试**

```python
def test_health_status_reports_sport_mode_safety_and_dds_state():
    status = build_health_status(
        now_sec=12.0,
        last_lowstate_sec=11.9,
        state_timeout_sec=0.3,
        pending_api_count=1,
        last_api_result={"code": 0},
        last_sport_response_sec=11.8,
        last_successful_mode_query_sec=11.7,
        mode_freshness_timeout_sec=1.5,
        consecutive_api_timeouts=1,
        api_unhealthy_timeout_count=3,
        last_command_ack={"sequence_id": 8, "state": "pending", "updated_monotonic_sec": 11.95},
        last_safety_heartbeat_sec=11.6,
        safety_heartbeat_timeout_sec=1.2,
    )
    assert status["state"] == "degraded"
    assert status["last_sport_response_age_ms"] == 200
    assert status["last_successful_mode_query_age_ms"] == 300
    assert status["mode_fresh"] is True
    assert status["safety_control_fresh"] is True
    assert status["dds_connection_state"] == "degraded"
    assert status["last_command_ack"]["age_ms"] == 50
    assert "updated_monotonic_sec" not in status["last_command_ack"]


def test_health_status_marks_stale_lowstate_and_repeated_api_timeouts_unhealthy():
    base = dict(
        now_sec=12.0,
        pending_api_count=0,
        last_api_result=None,
        last_sport_response_sec=11.9,
        last_successful_mode_query_sec=11.9,
        mode_freshness_timeout_sec=1.5,
        api_unhealthy_timeout_count=3,
        last_command_ack=None,
        last_safety_heartbeat_sec=11.9,
        safety_heartbeat_timeout_sec=1.2,
    )
    stale = build_health_status(
        **base, last_lowstate_sec=11.0, state_timeout_sec=0.3, consecutive_api_timeouts=0
    )
    api_down = build_health_status(
        **base, last_lowstate_sec=11.9, state_timeout_sec=0.3, consecutive_api_timeouts=3
    )
    assert stale["state"] == "unhealthy"
    assert stale["dds_connection_state"] == "disconnected"
    assert api_down["state"] == "unhealthy"
    assert api_down["dds_connection_state"] == "degraded"
```

同时扩展诊断测试，断言 `diagnostic_level_for_state("unhealthy") == b"\x02"`；扩展准入测试，覆盖 safety heartbeat 缺失/过期、mode 缺失/过期、未确认命令、非 internal loco mode 和全部新鲜时允许。

- [x] **Step 2: 运行 helper 测试并确认失败**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests/test_node_helpers.py`
Expected: FAIL，现有函数签名和状态字段不足。

- [x] **Step 3: 实现纯函数状态优先级**

实现 `_age_ms(now_sec, last_sec)`；`build_health_status` 先计算所有 age/fresh 字段，再按以下优先级赋值：lowstate missing/stale 或 API timeout 达到阈值为 `unhealthy`；mode stale、safety stale、存在 API timeout、命令 `pending/rejected/timed_out` 为 `degraded`；否则 `ok`。DDS 状态为 lowstate 异常时 `disconnected`，健康非 ok 时 `degraded`，其余 `connected`。

`check_sport_command_allowed` 按顺序拒绝：lowstate、safety heartbeat、mode freshness、unresolved command acknowledgement、`mode != "sport_api_loco"` 或 `control_owner != "internal"`。

- [x] **Step 4: 运行 helper 测试并确认通过**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests/test_node_helpers.py`
Expected: PASS。

---

### Task 3: 使用单调时钟追踪 Sport API 与 safety heartbeat

**Files:**
- Modify: `src/g1_interface/g1_interface/node.py:224-438,454-500`
- Modify: `src/g1_interface/tests/test_asr_bridge_node.py`

**Interfaces:**
- Consumes: `time.monotonic`、`rclpy.clock.Clock(clock_type=ClockType.STEADY_TIME)`、Task 1 配置、Task 2 准入和健康函数。
- Produces: `on_safety_state(msg)`、`watchdog_tick()`、`shutdown()`、`last_sport_response_monotonic_sec`、`last_successful_mode_query_monotonic_sec`、`consecutive_api_timeouts`、`last_command_ack`。

- [x] **Step 1: 扩展 FakeNode 与失败测试**

```python
class ManualMonotonicClock:
    def __init__(self, value=10.0):
        self.value = value
    def __call__(self):
        return self.value


def test_g1_interface_subscribes_to_safety_heartbeat_and_creates_watchdog_timer():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=ManualMonotonicClock())
    assert [topic for topic, callback in node.subscriptions if callback == bridge.on_safety_state] == ["/g1/state/safety"]
    assert any(period == pytest.approx(0.05) and callback == bridge.watchdog_tick for period, callback, clock in node.timers)


def test_successful_mode_response_updates_monotonic_freshness():
    clock = ManualMonotonicClock(10.0)
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=clock)
    bridge.query_sport_mode()
    request = next(
        item for item in node.publishers["/api/sport/request"].messages
        if item.header.identity.api_id == 7002
    )
    clock.value = 10.1
    bridge.on_sport_response(_sport_response(request, payload={"data": 2}))
    assert bridge.last_successful_mode_query_monotonic_sec == 10.1
    assert bridge.consecutive_api_timeouts == 0
```

更新 `FakeNode.create_timer` 为 `create_timer(self, period, callback, callback_group=None, clock=None)`，保存三元组 `(period, callback, clock)`。

- [x] **Step 2: 运行节点测试并确认失败**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests/test_asr_bridge_node.py`
Expected: FAIL，构造器不接受 monotonic clock、没有 safety subscription/watchdog。

- [x] **Step 3: 接入单调时钟和 API 状态**

构造器增加可选参数 `monotonic_clock: Callable[[], float] | None = None`，默认 `time.monotonic`。lowstate freshness、SportApiClient 的 `build_request/record_response/expired_requests`、mode freshness和健康状态全部使用该时钟；ROS `_now_sec()` 只用于输出 stamp。

订阅 `project_topics["safety_state"]`，仅接受 JSON object 且 `node == "safety_control"` 的消息作为心跳。成功解析任意 Sport response 更新 `last_sport_response_monotonic_sec`；匹配响应复位 timeout 计数；成功 `get_fsm_mode` 更新 mode freshness。

- [x] **Step 4: 运行节点测试并确认通过**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests/test_asr_bridge_node.py`
Expected: PASS。

---

### Task 4: 实现本地停止、确认超时与 shutdown 安全路径

**Files:**
- Modify: `src/g1_interface/g1_interface/node.py:398-514,517-542`
- Modify: `src/g1_interface/tests/test_asr_bridge_node.py`

**Interfaces:**
- Consumes: Task 3 的单调时间和 Sport API 状态。
- Produces: `_publish_stop_request(reason, now_sec, force=False)`、幂等 watchdog stop、sequence-based command ack、shutdown stop。

- [x] **Step 1: 写 watchdog 失败测试**

```python
def test_motion_deadline_publishes_zero_velocity_once():
    clock, node, bridge = _ready_bridge()
    bridge.on_safe_loco(_string_msg(
        '{"validation_result":{"allowed":true},"vx":0.2,"vy":0.0,"vyaw":0.0,"duration_sec":1.0}'
    ))
    motion_request = node.publishers["/api/sport/request"].messages[-1]
    clock.value = 10.1
    bridge.on_sport_response(_sport_response(motion_request))
    clock.value = 11.01
    bridge.last_lowstate_monotonic_sec = clock.value
    bridge.last_safety_heartbeat_monotonic_sec = clock.value
    bridge.watchdog_tick()
    bridge.watchdog_tick()
    requests = node.publishers["/api/sport/request"].messages
    assert json.loads(requests[-1].parameter) == {"duration": 0.1, "velocity": [0.0, 0.0, 0.0]}
    assert len([r for r in requests if json.loads(r.parameter)["velocity"] == [0.0, 0.0, 0.0]]) == 1
    assert bridge.last_command_ack["stop_reason"] == "command_deadline"


def test_safety_heartbeat_loss_stops_active_motion():
    clock, node, bridge = _ready_bridge()
    bridge.on_safe_loco(_valid_loco(duration_sec=2.0))
    request = node.publishers["/api/sport/request"].messages[-1]
    clock.value = 10.1
    bridge.on_sport_response(_sport_response(request))
    clock.value = 11.21
    bridge.last_lowstate_monotonic_sec = clock.value
    bridge.watchdog_tick()
    assert bridge.last_command_ack["stop_reason"] == "safety_heartbeat_lost"


def test_unacknowledged_motion_timeout_triggers_stop():
    clock, node, bridge = _ready_bridge()
    bridge.on_safe_loco(_valid_loco(duration_sec=2.0))
    clock.value = 10.51
    bridge.last_lowstate_monotonic_sec = clock.value
    bridge.last_safety_heartbeat_monotonic_sec = clock.value
    bridge.watchdog_tick()
    assert bridge.last_command_ack["command_kind"] == "stop"
    assert bridge.last_command_ack["stop_reason"] == "command_unacknowledged"


def test_safe_stop_bypasses_stale_state_gates():
    clock = ManualMonotonicClock(10.0)
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=clock)
    bridge.on_safe_stop(_string_msg('{"validation_result":{"allowed":true},"action":"stop"}'))
    request = node.publishers["/api/sport/request"].messages[-1]
    assert json.loads(request.parameter)["velocity"] == [0.0, 0.0, 0.0]


def test_shutdown_publishes_stop_once():
    clock = ManualMonotonicClock(10.0)
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=clock)
    bridge.shutdown()
    bridge.shutdown()
    assert len(node.publishers["/api/sport/request"].messages) == 1
    assert bridge.last_command_ack["stop_reason"] == "shutdown"
```

- [x] **Step 2: 运行 watchdog 测试并确认失败**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests/test_asr_bridge_node.py`
Expected: FAIL，现有节点只清零缓存且没有 shutdown 方法。

- [x] **Step 3: 实现命令追踪和停止状态机**

每次 `set_velocity` 发布后从 `request.header.identity.id` 记录：

```python
self.last_command_ack = {
    "sequence_id": sequence_id,
    "state": "pending",
    "code": None,
    "command_kind": "motion" if nonzero else "stop",
    "stop_reason": stop_reason,
    "updated_monotonic_sec": now_sec,
}
```

收到匹配响应后改为 `acknowledged` 或 `rejected`；运动命令被拒绝时调用 `_publish_stop_request("command_rejected", now_sec)`。`watchdog_tick()` 先过期 API 请求并标记 `timed_out`，若过期的是未确认运动命令则发布 `command_unacknowledged` stop；再检查 active motion 的 lowstate、safety heartbeat 和 command deadline。只要已有 pending stop，就不重复发布；shutdown 通过 `force=True` 幂等发送一次。

修改 `main()` 保存 `bridge = G1InterfaceNode(...)`，并在 `destroy_node()` 前调用 `bridge.shutdown()`。

- [x] **Step 4: 运行 watchdog 节点测试并确认通过**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests/test_asr_bridge_node.py`
Expected: PASS。

---

### Task 5: 健康发布集成、文档和完整验证

**Files:**
- Modify: `src/g1_interface/g1_interface/node.py:487-514`
- Modify: `src/g1_interface/README.md`
- Test: `src/g1_interface/tests/test_asr_bridge_node.py`
- Test: `src/g1_interface/tests/test_node_helpers.py`

**Interfaces:**
- Consumes: Tasks 1-4 的状态字段与 watchdog。
- Produces: `/g1/state/health` 完整诊断字段以及运维说明。

- [x] **Step 1: 写健康发布集成测试**

```python
def test_publish_health_exposes_watchdog_and_sport_fields():
    bridge.publish_health()
    diagnostic = node.publishers["/g1/state/health"].messages[-1].status[0]
    values = {item.key: json.loads(item.value) for item in diagnostic.values}
    assert set([
        "last_sport_response_age_ms",
        "last_successful_mode_query_age_ms",
        "consecutive_api_timeouts",
        "last_command_ack",
        "mode_fresh",
        "safety_control_age_ms",
        "safety_control_fresh",
        "dds_connection_state",
    ]).issubset(values)
```

- [x] **Step 2: 运行集成测试并确认失败**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests/test_asr_bridge_node.py`
Expected: FAIL，publish_health 尚未传入全部状态。

- [x] **Step 3: 接入健康发布并更新 README**

`publish_health()` 调用统一的 API expiry 方法，然后把所有单调状态传给 `build_health_status`；README 说明 watchdog 触发条件、默认 timeout、`unhealthy=ERROR` 以及 stop 不受 freshness gate 限制。

- [x] **Step 4: 运行完整测试集**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m pytest -q src/g1_interface/tests`
Expected: 所有测试 PASS，0 failures。

- [x] **Step 5: 检查 diff 和语法**

Run: `git diff --check && PYTHONPATH=src/g1_interface /home/ubuntu/Desktop/unitree_g1_agent/.venv/bin/python -m compileall -q src/g1_interface/g1_interface src/g1_interface/tests`
Expected: exit code 0，无 whitespace error 或 SyntaxError。
