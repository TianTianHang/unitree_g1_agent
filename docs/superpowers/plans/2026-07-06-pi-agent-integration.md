# Pi Agent 子进程接入设计 (v3)

**目标:** 在 `src/voice_bridge` 中新增 `PiRpcAgentClient` 适配器，通过子进程 JSONL 桥接 Pi Agent runtime（`.agent-runtime/pi`），使 voice_bridge 能调用真实 LLM agent 进行语音交互决策，同时保持安全边界不变。

**日期:** 2026-07-06
**版本:** v3 — 修正 v2 审查意见（8 Major）

## 1. 背景和动机

当前 voice_bridge P0 已完成 `AgentClient` Protocol 适配层，有三个内置适配器：`RuleBasedAgentClient`（关键词匹配）、`HttpJsonAgentClient`（HTTP JSON 请求）、`DisabledAgentClient`。这些适配器用于开发和测试，但缺乏真正的语言理解能力。

Pi Agent runtime（`.agent-runtime/pi` v0.80.3）是一个 Node.js monorepo，提供：
- 多 provider LLM 支持（OpenAI/Anthropic/Google/Bedrock/Mistral 等）
- `--mode rpc` 子进程模式：stdin/stdout JSONL 通信
- 完整的 tool calling 系统（内置 read/bash/edit/write/grep/find/ls + 自定义 tool）
- Session 持久化、compaction、extension 系统

本设计将 Pi 作为 voice_bridge 的 agent 后端，通过子进程 JSONL 桥接，实现语音到运动意图的智能转换。

## 2. 设计约束

1. **运动发布边界不变**: 在 `robot_*` tool → ROS topic 的映射路径上，voice_bridge 是唯一的运动发布安全边界。Pi 可以使用内置 read/bash/edit/write/grep/find/ls 等工具，但只有 `robot_*` 自定义 tool 的结果会被 Python 端映射为机器人命令，且必须通过验证后才发布运动；这不表示 Pi 进程本身被沙箱化。
2. **AgentClient Protocol 扩展兼容**: 新适配器实现扩展后的 Protocol（含 `abort()` 和 `close()`），现有适配器不受影响。
3. **Pi 运行边界**: Pi 子进程运行在指定工作区（`.agent-runtime/.unitree_agent`），清理 ROS2/DDS 环境变量以降低误接入 ROS graph 的概率；这不是 OS 级沙箱，文件/命令工具能力按当前用户权限保留。如需阻止 Pi 进程通过 bash/文件系统/本机工具绕过 voice_bridge，必须额外使用容器、VM、受限用户或 PATH allowlist 等 OS 级隔离。
4. **失败不产生运动**: Pi 崩溃、超时、parse 错误、返回非法结果 → 不发布任何运动命令。
5. **停止词绕过 agent 并可中断**: 停止词检测在 voice_bridge 内完成，不经过 Pi；停止词可中断正在运行的 Pi turn。
6. **P0 范围**: 单次 ASR → agent → command(s)，允许一个 turn 返回多条运动命令并按 tool call 顺序发布；`--no-session` 下只保留 Pi 进程内上下文复用，不承诺跨进程 session 持久化，流式 TTS 为 P1。

## 3. 架构

```text
voice_bridge (Python ROS2 node)
  │
  ├─ 停止词 → invalidate() → 直接发布 /voice/cmd/action → abort() (绕过 Pi)
  │
  └─ 普通 ASR → PiRpcAgentClient.decide()
       │
       ├─ 子进程: pi --mode rpc --no-session
       │    -e <robot-tools.ts路径>        # 显式加载自定义 tool
       │    --model <model> --provider <provider>  # 可选
       │    cwd: .agent-runtime/.unitree_agent
       │    session: 进程内 in-memory session（不落盘）
       │    通信: stdin/stdout JSONL (LF-only framing)
       │
       ├─ 事件流 (stdout):
       │    message_update.assistantMessageEvent → P1 流式 TTS
       │    tool_execution_start/end                → 累积自定义 tool call
       │    agent_end                               → 汇总 AgentResult
       │
       └─ 输出: AgentResult(commands, reply_text)
            │
            ├─ loco → /voice/cmd/loco
            ├─ action → /voice/cmd/action
            └─ say → /g1/cmd/audio/tts
```

## 4. AgentClient Protocol 扩展

### 4.1 问题：现有 Protocol 无法中断和关闭

现有 `AgentClient` Protocol 只有 `decide()`，无法：
- 中断正在运行的 `decide()` 调用（停止词到达时）
- 关闭子进程资源（节点 shutdown 时）

### 4.2 设计：OptionalCloseableAgent

不修改现有 `AgentClient` Protocol，定义一个新的子 Protocol，voice_bridge 检查 agent 是否支持扩展接口：

```python
class AgentClient(Protocol):
    """现有 Protocol，所有适配器必须实现。"""
    def decide(self, request: AgentRequest) -> AgentResult:
        ...

class OptionalCloseableAgent(Protocol):
    """可选扩展接口。Pi 适配器实现，其他适配器不需要。"""
    def abort(self) -> None:
        """中断正在运行的 decide() 调用。decide() 应尽快返回空 AgentResult。
        此方法不阻塞，通过设置标志位让 decide() 自行退出。"""
        ...

    def close(self) -> None:
        """释放子进程等资源。节点 shutdown 时调用。此方法阻塞，包含进程终止和线程回收。"""
        ...
```

### 4.3 node.py 改动

使用 `hasattr` 检测扩展接口，避免 `isinstance` 对普通 Protocol 失败：

```python
def _supports_closeable(agent) -> bool:
    return hasattr(agent, "abort") and hasattr(agent, "close")

class VoiceBridgeNode:
    def __init__(self, node, config: VoiceBridgeConfig, agent: AgentClient | None = None):
        ...
        self.agent = agent or build_agent(config)
        # 检测扩展接口（hasattr 检测，不用 isinstance）
        self._closeable_agent = self.agent if _supports_closeable(self.agent) else None

    def _publish_action_decision(self, decision: SessionDecision, now_sec: float) -> None):
        ...
        if action in {"stop", "cancel"}:
            self._agent_requests.invalidate()
            # 先发布 stop/cancel action（安全优先，确保运动停止不依赖 abort 完成）
            payload = build_action_payload(action=action, ..., priority="emergency")
            self._publish_string(self.action_pub, payload)
            # 再非阻塞 abort Pi（只设置标志位 + fire-and-forget 通知）
            if self._closeable_agent:
                self._closeable_agent.abort()
            return
        payload = build_action_payload(...)
        self._publish_string(self.action_pub, payload)
        ...

    def shutdown(self) -> None:
        self._agent_requests.invalidate()
        if self._closeable_agent:
            self._closeable_agent.close()          # 阻塞，关闭 Pi 子进程
        self._agent_executor.shutdown(wait=False, cancel_futures=True)
```

### 4.4 decide() 内部的中断机制

`PiRpcAgentClient.decide()` 在 `ThreadPoolExecutor` 中运行。中断流程：

```python
class PiRpcAgentClient:
    def __init__(self, config):
        ...
        self._aborted = threading.Event()  # 中断标志

    def abort(self) -> None:
        """中断正在运行的 decide()。非阻塞，只设置标志位让 decide() 自行退出。
        通知 Pi 的 abort 命令通过 fire-and-forget 在后台发送（短超时 1s）。
        同时唤醒事件队列，避免 decide() 卡在 get_event(timeout=...)。"""
        self._aborted.set()
        self._transport.wake_events(reason="aborted")
        def _send_abort():
            try:
                self._transport.send({"type": "abort"}, timeout=1.0)
            except PiTransportError:
                pass
        threading.Thread(target=_send_abort, daemon=True).start()

    def decide(self, request: AgentRequest) -> AgentResult:
        self._aborted.clear()
        self._current_result = AgentResult()
        _normal_completion = False  # 跟踪是否收到 agent_end
        transport_generation = self._transport.current_generation()
        try:
            # ... 事件循环 ...
            while not self._aborted.is_set():
                event = self._transport.get_event(
                    expected_generation=transport_generation,
                    timeout=...,
                )
                if event is None:
                    break  # 超时
                if event.get("type") == "_transport_wakeup":
                    break  # abort/close/crash 唤醒
                # ... 处理事件 ...
                # agent_end 到达时设置 _normal_completion = True
        finally:
            self._aborted.clear()
        # 中断/超时/异常：清除运动命令，保留 TTS 和 LED
        if not _normal_completion:
            self._current_result = AgentResult(
                reply_text=self._current_result.reply_text,
                led=self._current_result.led,
                commands=[],  # 不返回任何运动命令
            )
        return self._current_result
```

## 5. 子进程生命周期

### 5.1 启动命令构建

根据配置动态构建 Pi 启动命令，确保配置项正确映射到 CLI 参数：

```python
def _build_pi_command(pi_config: dict, workspace: Path) -> list[str]:
    cmd = [pi_config.get("command", "pi")]
    cmd.extend(pi_config.get("args", ["--mode", "rpc", "--no-session"]))
    
    if pi_config.get("model"):
        cmd.extend(["--model", pi_config["model"]])
    if pi_config.get("provider"):
        cmd.extend(["--provider", pi_config["provider"]])
    
    # 显式加载 robot-tools 扩展
    robot_tools = workspace / ".pi" / "extensions" / "robot-tools.ts"
    if robot_tools.exists():
        cmd.extend(["-e", str(robot_tools)])
    
    # 额外扩展目录
    for ext in pi_config.get("extensions", []):
        cmd.extend(["-e", ext])
    
    return cmd
```

### 5.2 Workspace 路径解析

路径通过 `pi_config.py` 解析，由 `PiRpcAgentClient.__init__` 传入仓库根目录，不依赖 `__file__` 的相对位置：

```python
# pi_config.py
DEFAULT_PI_WORKSPACE = Path(".agent-runtime") / ".unitree_agent"

def resolve_workspace(pi_config: dict, repo_root: Path) -> Path:
    """解析 Pi 工作区路径。优先使用配置值，否则默认相对于仓库根目录。"""
    raw = pi_config.get("workspace", "")
    path = Path(raw) if raw else DEFAULT_PI_WORKSPACE
    if not path.is_absolute():
        path = repo_root / path
    return path
```

`PiRpcAgentClient.__init__` 从 voice_bridge.yaml 解析时获取仓库根目录，传给 `resolve_workspace`。

`repo_root` 的确定方式：config 加载时从 config 文件路径向上搜索 `.git` 目录，或由节点启动参数显式传入。不依赖 `__file__` 相对位置。

### 5.2a 启动状态转换

子进程启动成功后，transport 进入 `RUNNING` 状态。`PiRpcTransport` 实例只启动一次；崩溃或关闭后由 `PiRpcAgentClient` 丢弃旧实例并创建新的 transport 重启，避免 `CLOSED -> RUNNING` 的状态复用歧义。
```python
def start(self, command: list[str], cwd: Path, env: dict[str, str]) -> None:
    with self._state_lock:
        if self._state != PiRpcTransport._State.IDLE:
            raise PiTransportError(f"cannot start from state {self._state.name}")
    self._proc = subprocess.Popen(
        command, cwd=cwd, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,  # 独立进程组，方便 killpg
    )
    self._reader_thread = threading.Thread(target=self._reader, daemon=True)
    self._stderr_thread = threading.Thread(target=self._stderr_reader, daemon=True)
    self._reader_thread.start()
    self._stderr_thread.start()
    with self._state_lock:
        self._state = PiRpcTransport._State.RUNNING
```

### 5.3 环境变量清理

```python
def scrubbed_env(pi_config: dict) -> dict[str, str]:
    """清理环境变量，移除 ROS2/DDS/SSH/机器人凭证。"""
    env = dict(os.environ)
    block_patterns = ("ROS_", "RMW_", "CYCLONEDDS_", "SSH_", "GIT_SSH_")
    
    # 要保留的变量
    keep = set(pi_config.get("env_keep", [
        "HOME", "PATH", "NODE_PATH",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    ]))
    keep = {key for key in keep if not key.startswith(block_patterns)}
    
    for key in list(env.keys()):
        if key not in keep and any(key.startswith(p) for p in block_patterns):
            del env[key]
    
    # 注入额外变量
    for key, value in pi_config.get("env_extra", {}).items():
        if key.startswith(block_patterns):
            continue  # 不允许注入被隔离的 ROS/DDS/SSH 变量
        env[key] = str(value)
    
    return env
```

注意：保留 `PATH` 是为了让 `pi`、`node`、包管理器和内置 bash tool 可运行，不是安全边界。部署到机器人时如需进一步限制 Pi 的本机命令能力，应通过 `env_keep/env_extra` 提供最小 PATH，或把整个 Pi 进程放入受限用户、容器、VM 等 OS 级隔离环境。

### 5.4 健康检查

- 启动后发送 `get_state` 命令，等待 `RpcResponse`，超时 15-30s
- `get_state` 响应结构（来自 rpc-types.ts）：
  ```json
  {"type": "response", "command": "get_state", "success": true, "data": {"sessionId": "...", "isStreaming": false, ...}}
  ```
- 成功前标记为 unhealthy，所有 agent 请求返回空 AgentResult（不发运动）
- 空闲时定期（每 30s）`get_state`，活跃时用 `last_event_at` 判断（超过 60s 无事件视为异常）

### 5.5 异常重启

崩溃检测（stdout EOF 或进程退出）：
1. 通过 `_bump_generation()` 原子递增 generation 计数
2. **唤醒所有 pending requests**（put 错误到 pending queues），避免请求等到超时
3. **唤醒事件等待者**（put `_transport_wakeup`），避免 `decide()` 卡在 `get_event(timeout=...)`
4. **清空旧 generation 事件**（drain 旧 generation 的 `_events`），丢弃所有旧事件
5. 标记当前 turn 为 failed
6. 丢弃旧 `PiRpcTransport` 实例，创建新实例后指数 backoff 重启（1s, 2s, 4s, 最大 30s）
7. 连续失败 5 次后回退到空 AgentResult 行为，记录错误

### 5.6 关闭

关闭逻辑完全收敛到 `PiRpcTransport.close()`。`PiRpcAgentClient.close()` 只做委托。
**不调用 `abort()`**：进程终止本身就是中断，abort 通知在关闭路径上无意义且可能阻塞。

```python
# PiRpcTransport.close()
def close(self) -> None:
    """关闭 Pi 子进程。线程安全，幂等。"""
    with self._state_lock:
        if self._state != PiRpcTransport._State.RUNNING:
            return
        self._state = PiRpcTransport._State.CLOSING

    # 1. 唤醒所有 pending requests（避免 send() 等到超时）
    with self._pending_lock:
        for q in self._pending.values():
            try:
                q.put({"type": "response", "success": False, "error": "transport closing"})
            except queue.Full:
                pass
        self._pending.clear()

    # 2. 唤醒正在 get_event() 的 decide()，再清理旧事件
    self.wake_events(reason="closing")
    while not self._events.empty():
        try:
            generation, event = self._events.get_nowait()
            if event.get("type") == "_transport_wakeup":
                self._events.put((generation, event))
                break
        except queue.Empty:
            break

    # 3. 终止进程组
    with self._state_lock:
        proc = self._proc
        self._proc = None
    if proc is not None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            os.killpg(proc.pid, signal.SIGKILL)

    # 4. 关闭线程
    if self._reader_thread:
        self._reader_thread.join(timeout=2)
    if self._stderr_thread:
        self._stderr_thread.join(timeout=2)

    with self._state_lock:
        self._state = PiRpcTransport._State.CLOSED

# PiRpcAgentClient.close()
def close(self) -> None:
    """委托给 transport。"""
    if self._transport is not None:
        self._transport.close()
        self._transport = None
```

## 6. JSONL 传输层

### 6.1 PiRpcTransport

使用 threading 模式（不使用 asyncio，与现有 rclpy + ThreadPoolExecutor 兼容）。

```python
class PiRpcTransport:
    """JSONL 传输层。线程安全，有明确生命周期状态。"""

    _State = Enum("State", "IDLE RUNNING CLOSING CLOSED")

    def __init__(self):
        self._state: PiRpcTransport._State = PiRpcTransport._State.IDLE
        self._state_lock = threading.Lock()     # 保护 _state, _generation
        self._proc: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()     # 保护 _pending
        self._pending: dict[str, queue.Queue] = {}   # request_id → response queue
        self._events: queue.Queue[tuple[int, dict]] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._generation: int = 0

    def _get_generation(self) -> int:
        with self._state_lock:
            return self._generation

    def current_generation(self) -> int:
        return self._get_generation()

    def _bump_generation(self) -> int:
        with self._state_lock:
            self._generation += 1
            return self._generation

    def wake_events(self, reason: str) -> None:
        """唤醒 get_event() 等待者。只作为本地 sentinel，不来自 Pi RPC。"""
        self._events.put((self._get_generation(), {"type": "_transport_wakeup", "reason": reason}))
```

### 6.2 Reader 线程

```python
def _reader(self):
    try:
        for raw_line in self._proc.stdout:
            line = raw_line.rstrip(b"\n")
            if line.endswith(b"\r"):
                line = line[:-1]
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # 跳过格式错误的行

            msg_id = msg.get("id")
            if msg.get("type") == "response" and msg_id:
                with self._pending_lock:
                    q = self._pending.pop(msg_id, None)
                if q is not None:
                    q.put(msg)
                    continue
            self._events.put((self._get_generation(), msg))
    except Exception:
        pass  # EOF 或进程退出
    finally:
        # 标记非 RUNNING，递增 generation，并唤醒所有等待者
        with self._state_lock:
            if self._state == PiRpcTransport._State.RUNNING:
                self._state = PiRpcTransport._State.CLOSED
                self._generation += 1
                generation = self._generation
            else:
                generation = self._generation
        # 唤醒所有 pending requests
        with self._pending_lock:
            for q in self._pending.values():
                try:
                    q.put({"type": "response", "success": False, "error": "transport closed"})
                except queue.Full:
                    pass
            self._pending.clear()
        self._events.put((generation, {"type": "_transport_wakeup", "reason": "closed"}))
```

关键：
- 严格按 `\n` 分割，`rstrip(b"\n")` 对 bytes 操作。Python file iteration 按 LF 分割（默认 text mode 是 universal newline，但 binary 模式按 LF）
- `json.loads` 异常不崩溃，跳过格式错误行
- **finally 块唤醒所有 pending requests 和 event waiters**，避免进程退出后请求卡在 `queue.get(timeout=...)` 或 `get_event(timeout=...)` 等待中
- `msg_id` 判空（Pi 的 prompt/abort 等异步命令的 response 可能无 id）
- Reader 使用 `_get_generation()` 读取当前 generation（而非直接访问 `_generation`），确保重启后新事件使用新 generation
- `get_event(expected_generation)` 丢弃过期 generation 事件，重启后旧事件不会被新 turn 消费
- `_state_lock` 保护 `_state` 和 `_generation`，send()/close()/restart() 之间有明确生命周期互斥

### 6.3 命令发送

```python
def send(self, command: dict, timeout: float = 5.0) -> dict:
    # 生命周期检查：不允许对 CLOSED/CLOSING 状态发送
    with self._state_lock:
        if self._state != PiRpcTransport._State.RUNNING:
            raise PiTransportError(f"transport not running (state={self._state.name})")
    request_id = uuid.uuid4().hex[:8]
    command = {**command, "id": request_id}
    response_q: queue.Queue = queue.Queue(maxsize=1)
    with self._pending_lock:
        self._pending[request_id] = response_q
    try:
        with self._write_lock:
            proc = self._proc
            if proc is None or proc.stdin is None:
                raise PiTransportError("transport process not available")
            proc.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        result = response_q.get(timeout=timeout)
        if result.get("success") is False:
            raise PiTransportError(result.get("error", "rpc command failed"))
        return result
    except BrokenPipeError:
        raise PiTransportError("broken pipe")
    except queue.Empty:
        raise PiTransportError("command timeout")
    finally:
        with self._pending_lock:
            self._pending.pop(request_id, None)
```

### 6.4 事件读取

```python
def get_event(self, expected_generation: int, timeout: float = 5.0) -> tuple[int, dict] | None:
    """读取事件，丢弃 generation 不匹配的过期事件。"""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            gen, msg = self._events.get(timeout=remaining)
        except queue.Empty:
            return None
        if gen == expected_generation:
            return (gen, msg)
        # 丢弃过期 generation 的事件（重启后旧事件）
```

## 7. 会话管理

### 7.1 Session 映射修正

`new_session` 的 RPC 响应（来自 rpc-types.ts）：
```json
{"type": "response", "command": "new_session", "success": true, "data": {"cancelled": boolean}}
```

`new_session` 响应**不含 `sessionId`**。获取 `sessionId` 必须后续调用 `get_state`：
```json
{"type": "response", "command": "get_state", "success": true, "data": {"sessionId": "...", ...}}
```

修正后的映射流程：
```python
async def _new_session(self) -> str | None:
    resp = self._transport.send({"type": "new_session"})
    if resp.get("data", {}).get("cancelled"):
        return None  # 上一个 session 的 turn 被取消
    # 获取 sessionId
    state_resp = self._transport.send({"type": "get_state"})
    return state_resp.get("data", {}).get("sessionId")
```

### 7.2 Session 复用策略

- P0 使用 `--no-session`：仅进程内上下文复用，不持久化到磁盘
- idle timeout（`idle_timeout_sec`，默认 20s）内：复用 Pi 进程内 session
- idle timeout 到期：发送 `new_session`，后续 `get_state` 获取新 sessionId
- voice_bridge 新会话（wake word）：发送 `new_session`
- Pi 崩溃重启后：自动获得新 session

### 7.3 Session ID 映射

```python
_pi_session_id: str | None = None  # 当前 Pi session ID（诊断用）
```

仅用于日志和调试，不用于安全决策。Pi 崩溃后置 `None`。

### 7.4 Prompt 上下文注入

```python
def _build_prompt_text(request: AgentRequest) -> str:
    context_parts = [f"session_id: {request.session_id}"]
    if request.robot_mode:
        context_parts.append(f"robot_mode: {request.robot_mode}")
    if request.safety_state:
        context_parts.append(f"safety_state: {request.safety_state}")
    if request.health_state:
        context_parts.append(f"health_state: {request.health_state}")
    context = "\n".join(context_parts)
    return f"Robot context:\n{context}\n\nUser said: {request.text}"
```

## 8. Tool Call → AgentResult 映射

### 8.1 自定义 Tool 定义

Pi 通过 `.pi/extensions/robot-tools.ts` 注册，**使用 `-e` 显式加载**（不依赖自动发现）。

| Tool 名 | 映射到 AgentCommand.kind | 参数 |
|---------|-------------------------|------|
| `robot_walk` | `loco` | `vx: number, vy: number, vyaw: number, duration_sec: number` |
| `robot_stop` | `action` | 无参数（Python 端映射为 `action="stop"`） |
| `robot_say` | `say` | `text: string` |
| `robot_led` | `led` | `r: number, g: number, b: number, ttl_sec: number` |

### 8.2 RPC 事件字段（来自 types.ts）

Pi Agent 的 tool execution 事件结构：
```typescript
// types.ts:426-428
{ type: "tool_execution_start"; toolCallId: string; toolName: string; args: any }
{ type: "tool_execution_update"; toolCallId: string; toolName: string; args: any; partialResult: any }
{ type: "tool_execution_end"; toolCallId: string; toolName: string; result: any; isError: boolean }
```

消息事件结构：
```typescript
// types.ts:423
{ type: "message_update"; message: AgentMessage; assistantMessageEvent: AssistantMessageEvent }
```

注意：`message_update` 没有顶层 `text_delta` 字段。文本增量在 `assistantMessageEvent` 内部，具体类型取决于 LLM provider。P1 流式 TTS 需要从 `assistantMessageEvent` 中提取文本。

### 8.3 事件累积

```python
CUSTOM_TOOLS = {"robot_walk": "loco", "robot_stop": "action", "robot_say": "say", "robot_led": "led"}

def on_tool_execution_start(event: dict) -> None:
    name = event.get("toolName", "")
    if name not in CUSTOM_TOOLS:
        return  # 忽略内置 tool；内置工具可执行，但不会映射为机器人命令
    pending_tools[event["toolCallId"]] = {
        "order": len(pending_tools),
        "tool_name": name,
        "kind": CUSTOM_TOOLS[name],
        "params": event.get("args", {}),
        "confirmed": False,
    }

def on_tool_execution_end(event: dict) -> None:
    # 使用 event 自身的 isError 字段，不检查 result 内容
    if event.get("isError", False):
        return  # tool 执行失败，不确认
    item = pending_tools.get(event.get("toolCallId"))
    if item:
        item["confirmed"] = True
```

### 8.4 Turn 完成后汇总

```python
def _build_agent_result(pending_tools: dict, reply_text: str | None) -> AgentResult:
    commands = []
    led_params: dict | None = None
    
    for item in sorted(pending_tools.values(), key=lambda x: x["order"]):
        if not item["confirmed"]:
            continue
        tool_name = item["tool_name"]
        kind = item["kind"]
        if tool_name == "robot_stop":
            commands.append(AgentCommand(kind="action", params={"action": "stop"}))
        elif kind == "led":
            led_params = item["params"]  # LED 不放入 commands，避免重复发布
        else:
            commands.append(AgentCommand(kind=kind, params=item["params"]))
    
    return AgentResult(commands=commands, reply_text=reply_text, led=led_params)
```

**修正**：`robot_led` 只映射到 `AgentResult.led`，不放入 `commands` 列表。现有 node.py 的 `_publish_agent_result` 会分别处理 `commands`（逐个发布到对应 topic）和 `result.led`（单独发布到 LED topic），如果 `robot_led` 同时出现在两者中会导致 LED 重复发布。

运动 tool call 的汇总规则：
- 只处理已确认且 `isError == False` 的 `robot_walk` / `robot_stop`；Pi 内置 `bash/read/write/edit/read/grep/find/ls` 等工具事件不进入运动命令列表
- 不做去重，不做全局覆盖；多个 `robot_walk` 和 `robot_stop` 按 Pi tool call/start 顺序逐条进入 `AgentResult.commands`
- `robot_stop` 只是序列中的一条 `AgentCommand(kind="action", params={"action": "stop"})`
- 每条命令在 Python 端独立 validate/clamp；非法参数只丢弃对应命令，不影响同一 turn 内其他有效命令

顺序约束：Pi 默认可并行执行同一 assistant message 里的多个 tool call，`tool_execution_end` 可能按完成顺序到达。因此 Python 端记录 `tool_execution_start` 顺序作为发布顺序；同时 `robot_walk` / `robot_stop` 的 extension 定义设置 `executionMode: "sequential"`，让 motion tool 的 start/end 顺序一致，降低测试和诊断歧义。

### 8.5 Reply text 提取

reply text 从 `message_update` 事件的 `assistantMessageEvent` 中提取（P1 实现细节取决于 LLM provider 的具体格式）：

```python
def _extract_reply_text(events: list[dict]) -> str | None:
    """从事件流中提取 agent 最终文本回复。"""
    parts = []
    for event in events:
        if event.get("type") == "agent_end":
            # agent_end 的 messages 包含完整对话，提取最后一条 assistant 消息
            for msg in reversed(event.get("messages", [])):
                if msg.get("role") == "assistant":
                    for block in msg.get("content", []):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
                    break
    return " ".join(parts).strip() if parts else None
```

### 8.6 voice_bridge 安全边界和运动安全规则（完整版）

Pi 进程不是沙箱：它可以使用 Pi runtime 提供的内置 `bash/read/write/edit/read/grep/find/ls` 等工具，能力边界等同于启动 Pi 的当前用户和清理后的环境变量。voice_bridge 是 `robot_*` 映射路径上的运动发布安全边界；只有 `robot_*` 自定义 tool 会被 Python 映射，其中只有 `robot_walk` 和 `robot_stop` 会产生 `loco` / `action` 运动命令，且所有映射结果必须经过 Python 端校验。

```python
VALID_ACTIONS = {"stop", "cancel", "stand", "resume"}

def _validate_and_clamp_loco(params: dict, config: VoiceBridgeConfig) -> dict | None:
    """验证并 clamp loco 参数。返回 None 表示验证失败。"""
    try:
        vx = float(params.get("vx", 0))
        vy = float(params.get("vy", 0))
        vyaw = float(params.get("vyaw", 0))
        duration_sec = float(params.get("duration_sec", 0))
    except (TypeError, ValueError):
        return None  # 非 finite 值
    
    # NaN/Inf 检查
    import math
    if any(math.isnan(v) or math.isinf(v) for v in [vx, vy, vyaw, duration_sec]):
        return None
    
    defaults = config.motion_defaults
    return {
        "vx": max(-defaults["default_vx"], min(defaults["default_vx"], vx)),
        "vy": max(-defaults["default_vy"], min(defaults["default_vy"], vy)),
        "vyaw": max(-defaults["default_vyaw"], min(defaults["default_vyaw"], vyaw)),
        "duration_sec": max(0.1, min(defaults["max_motion_duration_sec"], duration_sec)),
    }

def _validate_action(params: dict) -> dict | None:
    """验证 action 参数。只允许白名单内的 action。"""
    action = str(params.get("action", "stop"))
    if action not in VALID_ACTIONS:
        action = "stop"  # 未知 action 降级为 stop
    return {"action": action}

# 注意：_validate_action() 仅用于通用 action 命令的最终白名单校验。
# Pi 的 robot_stop 路径不读取 tool args 中的 action 字段，必须在
# _build_agent_result() 中硬编码为 {"action": "stop"}。

def _validate_led(params: dict) -> dict | None:
    """验证 LED 参数。"""
    try:
        import math
        r = float(params.get("r", 0))
        g = float(params.get("g", 0))
        b = float(params.get("b", 0))
        ttl_sec = float(params.get("ttl_sec", 1.0))
        if any(math.isnan(v) or math.isinf(v) for v in [r, g, b, ttl_sec]):
            return None
        return {
            "r": max(0, min(255, int(r))),
            "g": max(0, min(255, int(g))),
            "b": max(0, min(255, int(b))),
            "ttl_sec": max(0.1, min(30.0, ttl_sec)),
        }
    except (TypeError, ValueError):
        return None

def _sanitize_tts(text: object) -> str | None:
    """TTS 文本仅接受非空字符串，P0 截断到 200 字符。"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    return text[:200] if text else None

def _safety_allows_motion(safety_state: str | None) -> bool:
    """安全状态来自 AgentRequest.safety_state，不来自 Pi 事件。"""
    unsafe = {"emergency", "estop", "fault", "unsafe"}
    return (safety_state or "").lower() not in unsafe

def _filter_motion_commands(commands: list[AgentCommand], safety_state: str | None) -> list[AgentCommand]:
    """按 tool call/start 顺序保留所有有效运动命令；非安全状态下全部丢弃。"""
    if not _safety_allows_motion(safety_state):
        return []
    return [cmd for cmd in commands if cmd.kind in {"loco", "action"}]

def _finalize_agent_result(result: AgentResult, request: AgentRequest, config: VoiceBridgeConfig) -> AgentResult:
    finalized: list[AgentCommand] = []
    motion_candidates: list[AgentCommand] = []
    for cmd in result.commands:
        if cmd.kind == "loco":
            params = _validate_and_clamp_loco(cmd.params, config)
            if params is not None:
                motion_candidates.append(AgentCommand(kind="loco", params=params))
        elif cmd.kind == "action":
            params = _validate_action(cmd.params)
            if params is not None:
                motion_candidates.append(AgentCommand(kind="action", params=params))
        elif cmd.kind == "say":
            text = _sanitize_tts(cmd.params.get("text"))
            if text is not None:
                finalized.append(AgentCommand(kind="say", params={"text": text}))

    motion_commands = _filter_motion_commands(motion_candidates, request.safety_state)
    finalized = motion_commands + finalized

    led = _validate_led(result.led or {}) if result.led else None
    reply_text = _sanitize_tts(result.reply_text) if result.reply_text else None
    return AgentResult(commands=finalized, reply_text=reply_text, led=led)
```

运动限制：
- 一个 turn 可以包含多条运动命令（`loco` 或 `action`），按 Pi tool call/start 顺序保留并发布
- `robot_stop` 映射为序列中的 `action="stop"`，不覆盖或删除同一 turn 内的其他有效运动命令
- 单条命令参数非法时只丢弃该命令，不影响同一 turn 内其他已验证命令
- 安全状态来自 `AgentRequest.safety_state`；非安全状态下丢弃所有运动命令，保留 TTS/LED
- NaN/Inf 值拒绝；速度/时长/RGB/TTL 使用 Python 端硬 clamp
- action 只允许白名单值
- LED RGB 限制 0-255，TTL 限制 0.1-30s
- TTS 文本长度限制 200 字符（P0）

## 9. PiRpcAgentClient 实现

### 9.1 类结构

```python
class PiRpcAgentClient:
    """AgentClient + OptionalCloseableAgent 实现。"""
    
    def __init__(self, config: VoiceBridgeConfig):
        self._config = config
        self._pi_config = config.agent.get("pi", {})
        self._transport: PiRpcTransport | None = None
        self._shutdown_lock = threading.Lock()
        self._aborted = threading.Event()
        self._pi_session_id: str | None = None
        self._last_activity: float = 0.0
        self._current_result = AgentResult()  # 中断时返回此结果
        self._startup_lock = threading.Lock()  # 串行化启动
    
    def decide(self, request: AgentRequest) -> AgentResult:
        """实现 AgentClient Protocol。"""
        ...
    
    def abort(self) -> None:
        """实现 OptionalCloseableAgent。中断正在运行的 decide()。"""
        ...
    
    def close(self) -> None:
        """实现 OptionalCloseableAgent。释放子进程资源。"""
        ...
```

### 9.2 decide 流程（修正版）

```
decide(request)
  1. self._aborted.clear()
  2. self._current_result = AgentResult()  # 重置
  3. _normal_completion = False
  4. [启动保护] 确保 Pi 子进程存活（startup_lock 串行化启动/重启）
  5. 检查 session 复用（idle timeout → new_session → get_state）
  6. 发送 prompt 命令（含 robot context）
     - prompt response 是异步的（success: true，无 data）
  7. 事件循环（while not aborted）：
     a. message_update → P1: 记录 assistantMessageEvent
     b. tool_execution_start → 累积自定义 tool（忽略内置 tool）
     c. tool_execution_end → 确认 tool（检查 isError）
     d. agent_end → 提取 reply_text → _normal_completion = True → 退出循环
     e. 超时 → 发送 abort → 退出循环
     f. 异常 → 退出循环
 8. 如果 not _normal_completion：
     清空 _current_result.commands（保留 reply_text/led），返回
 9. 汇总 AgentResult（confirmed_tools + reply_text）
 10. 验证和 clamp 所有命令参数（失败则只丢弃该命令）
 11. 安全状态检查：如果 request.safety_state 表示非安全状态
     （如 "emergency"、"estop"），丢弃运动命令（保留 TTS/LED）
 12. 更新 _last_activity
 13. return _current_result
```

**关键规则**: 只有收到 `agent_end` 事件（`_normal_completion = True`）才允许汇总运动命令。
中断/超时/异常退出 → `commands` 被清空，返回的 `AgentResult` 最多包含 TTS 文本和 LED 状态。
node.py 的 generation 检查（9.3 节）是第二道防线：即使 decide() 返回了运动命令，
如果 generation 已过期，结果在 node 层也被丢弃。

### 9.3 代码调用链修正

`decide()` 本身不知道 node 层的 generation（review #5 的问题）。解决方案：
- **不在 `decide()` 内部检查 generation**，由 node.py 的 `_run_agent_request` 在调用前后检查
- `abort()` 只负责中断 Pi 子进程，generation invalidation 由 node.py 的 `_agent_requests.invalidate()` 完成
- 这样 `AgentClient` Protocol 保持不变，`PiRpcAgentClient` 只实现 `decide()` + 扩展的 `abort()`/`close()`

node.py 中的调用链不变：
```python
def _run_agent_request(self, request, generation, request_sec):
    if not self._agent_requests.is_current(generation, request.session_id):
        return
    try:
        result = self.agent.decide(request)
        if not self._agent_requests.is_current(generation, request.session_id):
            return  # generation 过期，丢弃结果
        ...
    except Exception:
        ...
```

## 10. 超时策略

```yaml
pi_timeouts:
  startup_health_sec: 20.0        # 启动健康检查
  command_response_sec: 5.0       # RPC 命令接受响应
  first_event_sec: 15.0           # 首个有用事件（text/tool）
  motion_turn_hard_sec: 25.0     # 运动命令 turn 硬截止
  conversational_turn_sec: 60.0  # 纯对话 turn
  idle_health_check_sec: 30.0    # 空闲时健康检查间隔
  stall_detection_sec: 60.0      # 无事件视为异常
  restart_backoff_max_sec: 30.0  # 崩溃重启最大 backoff
  restart_max_attempts: 5        # 连续失败次数上限
```

## 11. 配置扩展

### 11.1 voice_bridge.yaml

```yaml
agent:
  backend: pi_rpc              # rule_based | http_json | pi_rpc | disabled
  http_endpoint: ""             # http_json 时使用
  timeout_sec: 2.0              # 非 pi_rpc 时的 agent 超时
  pi:
    enabled: true
    command: "pi"              # Pi 可执行文件路径
    workspace: ".agent-runtime/.unitree_agent"  # 相对于仓库根目录
    model: ""                     # 空 = 使用 Pi 默认模型
    provider: ""                # 空 = 使用 Pi 默认 provider
    extensions: []               # 额外 -e 扩展目录
    env_keep:
      - HOME
      - PATH
      - NODE_PATH
      - ANTHROPIC_API_KEY
      - OPENAI_API_KEY
      - GEMINI_API_KEY
    env_extra: {}                # 额外环境变量（不允许 ROS_/RMW_/CYCLONEDDS_/SSH_/GIT_SSH_ 前缀）
    timeouts:
      startup_health_sec: 20.0
      command_response_sec: 5.0
      first_event_sec: 15.0
      motion_turn_hard_sec: 25.0
      conversational_turn_sec: 60.0
      idle_health_check_sec: 30.0
      stall_detection_sec: 60.0
      restart_backoff_max_sec: 30.0
      restart_max_attempts: 5
```

### 11.2 config.py 校验扩展

```python
def validate(self) -> None:
    ...
    # 已有校验
    backend = self.agent.get("backend")
    if backend not in {"rule_based", "http_json", "pi_rpc", "disabled"}:
        raise ValueError(f"unsupported agent backend: {backend}")
    _require_number(self.agent, "timeout_sec", positive=True)
    if backend == "http_json" and not self.agent.get("http_endpoint"):
        raise ValueError("http_json backend requires http_endpoint")
    
    # pi_rpc 校验
    if backend == "pi_rpc":
        pi = self.agent.get("pi", {})
        if not isinstance(pi, dict):
            raise ValueError("agent.pi must be a mapping")

        enabled = pi.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("agent.pi.enabled must be boolean")
        if not enabled:
            raise ValueError("agent.backend=pi_rpc requires agent.pi.enabled=true")

        pi_command = pi.get("command", "pi")
        if not isinstance(pi_command, str) or not pi_command:
            raise ValueError("agent.pi.command must be non-empty string")

        workspace = pi.get("workspace", ".agent-runtime/.unitree_agent")
        if not isinstance(workspace, str):
            raise ValueError("agent.pi.workspace must be string")
        args = pi.get("args", ["--mode", "rpc", "--no-session"])
        if not isinstance(args, list) or not all(isinstance(v, str) for v in args):
            raise ValueError("agent.pi.args must be list[str]")
        extensions = pi.get("extensions", [])
        if not isinstance(extensions, list) or not all(isinstance(v, str) for v in extensions):
            raise ValueError("agent.pi.extensions must be list[str]")

        if pi.get("model") is not None and not isinstance(pi.get("model"), str):
            raise ValueError("agent.pi.model must be string")
        if pi.get("provider") is not None and not isinstance(pi.get("provider"), str):
            raise ValueError("agent.pi.provider must be string")

        blocked_prefixes = ("ROS_", "RMW_", "CYCLONEDDS_", "SSH_", "GIT_SSH_")
        if "env_keep" in pi:
            _require_string_list(pi, "env_keep")
            for key in pi["env_keep"]:
                if key.startswith(blocked_prefixes):
                    raise ValueError(f"agent.pi.env_keep key '{key}' is not allowed")
        env_extra = pi.get("env_extra", {})
        if not isinstance(env_extra, dict):
            raise ValueError("agent.pi.env_extra must be mapping")
        for key in env_extra:
            if not isinstance(key, str):
                raise ValueError("agent.pi.env_extra keys must be strings")
            if key.startswith(blocked_prefixes):
                raise ValueError(f"agent.pi.env_extra key '{key}' is not allowed")

        # 校验 timeout 子字段
        pi_timeouts = pi.get("timeouts", {})
        if not isinstance(pi_timeouts, dict):
            raise ValueError("agent.pi.timeouts must be mapping")
        for key in [
            "startup_health_sec",
            "command_response_sec",
            "first_event_sec",
            "motion_turn_hard_sec",
            "conversational_turn_sec",
            "idle_health_check_sec",
            "stall_detection_sec",
            "restart_backoff_max_sec",
        ]:
            if key in pi_timeouts:
                _require_number(pi_timeouts, key, positive=True)
        if "restart_max_attempts" in pi_timeouts:
            attempts = pi_timeouts["restart_max_attempts"]
            if not isinstance(attempts, int) or attempts <= 0:
                raise ValueError("agent.pi.timeouts.restart_max_attempts must be positive integer")
```

## 12. Pi 扩展：robot-tools

### 12.1 文件位置

`.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts`

### 12.2 加载方式

通过 Pi CLI 的 `-e` 参数显式加载：
```bash
pi --mode rpc --no-session -e .agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts
```

不依赖 Pi 的自动发现或 trust/settings 机制，确保扩展一定会被加载。

### 12.3 Tool 定义

- `robot_walk`：参数 `vx(number, -1~1)`, `vy(number, -1~1)`, `vyaw(number, -1~1)`, `duration_sec(number, 0.1~10)`，描述为"控制机器人移动方向和持续时间"
- `robot_stop`：**无参数**，描述为"立即停止机器人运动"
- `robot_say`：参数 `text(string)`，描述为"通过 TTS 输出语音"
- `robot_led`：参数 `r(number, 0~255)`, `g(number, 0~255)`, `b(number, 0~255)`, `ttl_sec(number, 0.1~30)`，描述为"控制 LED 颜色"

`robot_walk` 和 `robot_stop` 必须设置 `executionMode: "sequential"`。tool 执行为空操作（仅返回参数作为 tool result），所有实际执行由 voice_bridge 完成。`robot_stop` 的返回参数不参与 action 推导，Python 端始终硬编码为 `action="stop"`。

### 12.4 System Prompt

在 Pi 的 system prompt 中通过 appendSystemPrompt 注入（CLI 参数 `--append-system-prompt`，内部字段名为 `appendSystemPrompt`，或 extension hook）：
- 说明可用的 robot tool 及其参数范围
- 说明每次交互应主动调用合适的 tool
- 说明运动指令应基于用户意图和机器人当前状态
- **注意**：安全策略（速度限制、时长限制、安全状态检查）不在 prompt 中，而是由 Python 端硬规则保证

## 13. 实现结构

```text
src/voice_bridge/
├── voice_bridge/
│   ├── agent.py              # 已有：AgentClient Protocol + 旧适配器
│   ├── pi_agent.py           # 新增：PiRpcAgentClient, PiRpcTransport
│   ├── pi_config.py          # 新增：Pi 子进程配置解析、workspace 路径、scrubbed_env
│   ├── pi_types.py           # 新增：Pi RPC 事件类型常量、OptionalCloseableAgent
│   ├── config.py             # 已有：扩展 validate 支持 pi_rpc
│   ├── internal_types.py     # 已有：无需修改
│   ├── intent.py             # 已有：无需修改
│   └── node.py               # 已有：扩展 shutdown 支持 close()
├── tests/
│   ├── test_pi_transport.py  # 新增：PiRpcTransport 单元测试
│   ├── test_pi_agent.py      # 新增：PiRpcAgentClient 单元测试
│   ├── test_pi_config.py     # 新增：Pi 配置解析测试
│   └── test_pi_types.py      # 新增：事件解析、参数验证测试
└── config/voice_bridge.yaml  # 扩展 agent.pi 配置

.agent-runtime/
├── pi/                       # Pi runtime 源码（已有）
└── .unitree_agent/           # 新增：Pi 工作区
    └── .pi/
        └── extensions/
            └── robot-tools.ts  # 自定义 robot tool
```

## 14. build_agent_client 扩展

```python
def build_agent_client(config: VoiceBridgeConfig) -> AgentClient:
    backend = config.agent["backend"]
    if backend == "rule_based":
        return RuleBasedAgentClient(config)
    if backend == "http_json":
        return HttpJsonAgentClient(config)
    if backend == "pi_rpc":
        from voice_bridge.pi_agent import PiRpcAgentClient
        return PiRpcAgentClient(config)
    return DisabledAgentClient()
```

## 15. 测试设计

### 15.1 PiRpcTransport 单元测试

- Mock subprocess stdin/stdout，验证 JSONL 帧解析
- 验证 command/response ID 关联
- 验证事件分发到 events queue
- 验证 generation 过期事件被丢弃
- 验证 stderr drain 不阻塞
- 验证 BrokenPipeError / EOF 处理
- 验证 **pending requests 在进程崩溃时被唤醒**（不再卡到超时）
- 验证 `abort()` / `close()` / crash 会通过 `_transport_wakeup` 唤醒正在 `get_event()` 的 decide loop
- 验证崩溃重启会丢弃旧 `PiRpcTransport` 并创建新实例，不复用 `CLOSED` transport
- 验证 **_pending_lock 线程安全**

### 15.2 PiRpcAgentClient 单元测试

- Mock PiRpcTransport，模拟事件流
- 验证正常流程：prompt → tool_execution_start/end → agent_end → AgentResult
- 验证运动参数 clamp
- 验证 NaN/Inf 拒绝
- 验证 action 白名单
- 验证 LED RGB/TTL 范围限制
- 验证多 tool call 的顺序，不去重、不合并、不用 stop 覆盖其他运动命令
- 验证多个 `robot_walk` 按 tool call/start 顺序全部保留并发布
- 验证多条运动命令按 tool call/start 顺序保留并发布
- 验证 `walk → stop → walk` 不被 stop 覆盖，三条有效运动命令均保留
- 验证 `robot_stop` 即使收到异常 args 也硬编码为 `action="stop"`，不会发布 `stand/resume/cancel`
- 验证非法参数只丢弃对应命令，同一 turn 内其他有效运动命令仍保留
- 验证安全状态不允许运动时丢弃所有 `loco` / `action`，但保留 TTS/LED
- 验证超时 → 返回空 AgentResult
- 验证 **abort() 中断 decide()**
- 验证 **Pi 未启动 → 返回空 AgentResult**（不 crash）
- 验证 **stop 期间 Pi 结果不被发布**

### 15.3 集成测试

- 启动 Pi 子进程，发送 `get_state`，验证响应结构
- 发送 `prompt`，验证事件流包含 `tool_execution_*` 事件
- 验证 `new_session` → `get_state` 流程
- 验证 `-e robot-tools.ts` 加载后 tool 列表包含自定义 tool
- 验证 Pi 崩溃后恢复

### 15.4 环境标记

```python
PI_AGENT_INTEGRATION = os.environ.get("PI_AGENT_INTEGRATION", "")

@pytest.mark.skipif(not PI_AGENT_INTEGRATION, reason="Pi not available")
class TestPiIntegration:
    ...
```

## 16. 分阶段交付

### Task 1: 基础设施

- [ ] `pi_types.py`：OptionalCloseableAgent Protocol、Pi RPC 事件类型常量
- [ ] `pi_config.py`：workspace 路径解析、scrubbed_env、命令构建、配置校验
- [ ] `config.py`：validate 扩展支持 `pi_rpc`
- [ ] `agent.py`：build_agent_client 扩展
- [ ] 单元测试：配置校验、workspace 路径、env scrub

### Task 2: PiRpcTransport

- [ ] `pi_agent.py`：PiRpcTransport（子进程启动、JSONL 读写、stderr drain、pending 唤醒）
- [ ] 单元测试：mock subprocess、JSONL 帧、ID 关联、pending 唤醒、线程安全

### Task 3: PiRpcAgentClient 核心

- [ ] `pi_agent.py`：PiRpcAgentClient（decide 事件循环、tool call 累积、abort/close）
- [ ] 参数验证：loco clamp + NaN 检查、action 白名单、LED 范围、TTS 长度
- [ ] `voice_bridge.yaml` 扩展
- [ ] 单元测试：mock transport、完整流程、参数验证、abort/close

### Task 4: Pi 扩展 robot-tools

- [ ] `.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts`
- [ ] 集成测试：验证 tool 加载和调用

### Task 5: node.py 集成和文档

- [ ] `node.py`：shutdown 支持 close()、stop 词支持 abort()
- [ ] 更新 README.md、设计文档实现状态
- [ ] 端到端集成测试

## 17. 验收标准

- `agent.backend: pi_rpc` 配置下，voice_bridge 能启动 Pi 子进程并保持健康
- ASR 文本经 Pi agent 处理后，只有 `robot_*` 自定义 tool call 会被 Python 映射；Pi 内置 tool 可参与推理和执行，但不映射为机器人命令
- 运动意图发布到 `/voice/cmd/loco` 和 `/voice/cmd/action`，经过 safety_control 验证
- 一个 turn 内多个 `robot_walk` / `robot_stop` 按 tool call/start 顺序逐条发布；`robot_stop` 不覆盖同一 turn 内其他运动命令
- 停止词、shutdown、Pi 崩溃都能唤醒等待中的 agent worker，不依赖长超时自然返回
- 非法运动参数只丢弃对应命令；安全状态不允许运动时丢弃所有 `loco` / `action`，保留 TTS/LED
- Pi 崩溃后自动恢复，恢复期间不发布运动
- idle timeout 后进程内 session 正确重建（`new_session` → `get_state`）；`--no-session` 不产生跨进程持久化 session
- 停止词绕过 agent 直接发布，**并能中断正在运行的 Pi turn**
- 节点 shutdown 时 Pi 子进程被正确清理
- Pi 的 bash/read/write 等内置 tool 正常工作但不映射为运动
- 单元测试覆盖 transport、agent client、config 解析、参数验证
- 集成测试在 `PI_AGENT_INTEGRATION=1` 下通过

## 附录 A：与 v1 的变更摘要

| 变更 | 原因 | 审查意见编号 |
|------|------|-------------|
| 新增 `OptionalCloseableAgent` Protocol | 解决 abort/close 需求 | Major #4, #6 |
| `abort()` 实现和 `_aborted` Event | 停止词可中断 Pi turn | Major #4 |
| `close()` 实现和 `_shutdown_lock` | 节点 shutdown 清理子进程 | Major #6 |
| `new_session` → `get_state` 获取 sessionId | RPC 类型修正 | Major #3 |
| `_build_pi_command()` 动态构建启动命令 | 配置项映射到 CLI 参数 | Major #9 |
| workspace 通过配置解析，不用 `__file__` | 路径计算修正 | Major #8 |
| `-e` 显式加载扩展 | 确保扩展被加载 | Major #10 |
| `robot_stop` 无参数，Python 映射为 `action="stop"` | 参数描述统一 | Minor #18 |
| `_pending_lock` 保护 `_pending` dict | 线程安全 | Major #13 |
| reader finally 唤醒 pending requests | 进程退出不卡死 | Major #15 |
| `isError` 直接从 event 字段读取 | RPC 事件结构修正 | Major #7 |
| `robot_led` 只映射到 `result.led` 不放入 commands | LED 避免重复发布 | Major #12 |
| NaN/Inf 检查、action 白名单、LED/TTL 限制 | 完整运动验证 | Major #11 |
| `config.py` validate 扩展 `pi_rpc` | 校验覆盖 | Major #14 |
| safety 策略从 prompt 移到 Python 硬规则 | 安全性 | Suggestion #21 |
| 保留 Pi 内置工具能力，澄清 Pi 不是 OS 级沙箱 | 用户确认内置工具允许使用 | v3 follow-up |
| 允许一个 turn 多条运动命令，按 tool 顺序发布 | 用户确认多运动命令允许使用 | v3 follow-up |

## 附录 B：v2 审查修正摘要

| v2 审查项 | v3 处理 |
|-----------|---------|
| `isinstance(self.agent, OptionalCloseableAgent)` 会因普通 Protocol 失败 | 使用 `hasattr(agent, "abort") and hasattr(agent, "close")`，不依赖 `@runtime_checkable` |
| 停止词路径可能被 `abort()` 阻塞 | stop/cancel 先发布 emergency action，再非阻塞 fire-and-forget abort |
| workspace 解析仍依赖 `__file__` | `resolve_workspace(pi_config, repo_root)` 由 config 路径或节点参数传入 repo root |
| abort/timeout 后可能返回已确认运动命令 | 只有收到当前 turn 的 `agent_end` 才允许汇总运动；中断/超时/异常清空 `commands` |
| transport generation/lifecycle 线程安全不足 | `_state_lock` 保护 `_state/_generation`，`get_event(expected_generation)` 丢弃旧事件，`send()` 对非 RUNNING 状态抛 `PiTransportError` |
| `close()` 类结构不一致且可能阻塞 | 关闭逻辑收敛到 `PiRpcTransport.close()`，`PiRpcAgentClient.close()` 只委托，不在 shutdown 路径调用 `abort()` |
| 配置校验不完整 | 补齐 `pi`/workspace/extensions/env/timeouts/restart 校验，并禁止 `env_keep/env_extra` 绕过 ROS/DDS/SSH 隔离 |
| 运动验证 edge case 未定义 | 明确 `request.safety_state` allow/deny、多运动命令保序发布、LED/TTS finite 和长度规则 |
| system prompt CLI 参数名错误 | 使用 `--append-system-prompt`；`appendSystemPrompt` 仅作为内部字段名 |
