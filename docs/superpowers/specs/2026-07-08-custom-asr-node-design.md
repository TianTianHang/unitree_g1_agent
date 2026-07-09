# 自建 ASR 节点设计

**日期**: 2026-07-08
**状态**: Draft
**相关包**: `src/asr_node`（新建）

---

## 1. 问题陈述

### 当前状态

G1 机器人内置 ASR 引擎运行在硬件端，识别结果通过 DDS topic `/audio_msg`（`std_msgs/msg/String`）发布。项目通过 `g1_interface` 将其桥接到项目内部 topic `/g1/audio/asr`，供 `voice_bridge` 消费。

**数据流**：

```
麦克风 → G1硬件内置ASR → /audio_msg → g1_interface → /g1/audio/asr → voice_bridge
```

### 动机

1. **内置 ASR 的局限**：G1 硬件端 ASR 引擎为闭源实现，无法自定义语言模型、热词、识别参数，中文识别质量有限。
2. **可控性**：自建 ASR 允许选择模型大小、语言、热词提示，以及未来的多语言、唤醒词检测等扩展。
3. **独立性**：不依赖 G1 硬件 ASR 服务，可以在模拟器环境中独立运行完整的语音识别链路。

### 音频源

G1 机器人麦克风音频通过 UDP 组播发送，SDK2 示例（`.unitree/unitree_sdk2/example/g1/audio/g1_audio_client_example.cpp`）展示了接收方式：

```cpp
#define GROUP_IP "239.168.123.161"
#define PORT 5555
#define WAV_LEN_ONCE (16000 * 2 * 160 / 1000)  // 160ms = 5120 bytes
```

- 组播地址：`239.168.123.161`
- 端口：`5555`
- 音频格式：16kHz, 16-bit LE PCM, mono
- 每包约 160ms（5120 bytes）
- 网络接口：需绑定 `192.168.123.x` 网卡

**注意**：这个 UDP 组播流与 DDS/CycloneDDS 完全独立。组播承载原始 PCM 音频，DDS topic `/audio_msg` 承载的是硬件端识别后的文本结果。

---

## 2. 技术选型

| 组件 | 技术 | 理由 |
|------|------|------|
| ASR 引擎 | faster-whisper (`medium`) | OpenAI Whisper 的优化实现，CTranslate2 后端，中文效果好，GPU 加速支持 |
| VAD | Silero VAD | 轻量（~2MB），准确度高，支持流式检测，可通过 torchaudio 直接加载 |
| 音频捕获 | Python `socket` (UDP 组播) | 复刻 SDK2 示例的 POSIX socket 逻辑 |
| 音频处理 | `numpy` | PCM 到 float32 转换，VAD 输入格式化 |
| ROS2 接口 | `rclpy` + `std_msgs/msg/String` | 与项目现有 Python ROS2 节点风格一致 |
| GPU 推理 | CUDA `float16` | 消费级 GPU（8-12GB），medium 模型显存 ~3GB |

### 模型选择

| 模型 | 大小 | 中文效果 | GPU 显存 | 推理速度 |
|------|------|----------|----------|----------|
| tiny | 75M | 差 | ~1GB | 极快 |
| base | 142M | 一般 | ~1GB | 很快 |
| small | 466M | 中等 | ~2GB | 快 |
| **medium** | **1.5G** | **较好** | **~3GB** | **中等** |
| large-v3 | 3G | 最好 | ~5GB | 较慢 |

选择 `medium`：中文效果较好，消费级 GPU 显存充裕，推理速度可接受（~0.5-1s/3s 音频）。

---

## 3. 架构

### 数据流

```
                         ┌─ 内置 ASR 路径（默认）────────────────────────┐
                         │  G1 硬件 ASR → /audio_msg                      │
                         │    → g1_interface.on_audio_msg()                 │
麦克风 → UDP 组播          │    → /g1/audio/asr                              │
  239.168.123.161:5555   │    → voice_bridge.on_asr()                      │
  16kHz 16bit LE PCM    ──┤                                                 │
                         │                                                 │
                         └─ 自建 ASR 路径（可选）────────────────────────┐
                            asr_node（新包）                                │
                              ├─ audio_capture.py: UDP 组播接收            │
                              │   (独立线程，阻塞 recvfrom)                  │
                              ├─ vad.py: Silero VAD 语音活动检测           │
                              ├─ buffer.py: 语音分段缓冲区                 │
                              └─ asr_engine.py: faster-whisper (medium)    │
                                   ↓                                       │
                              /g1/audio/asr                                 │
                                (source: "custom_asr")                     │
                                   ↓                                       │
                              voice_bridge.on_asr()  ←───────────────────┘
```

### 切换机制

切换方式为启停 `asr_node` 包：

- **使用内置 ASR**：不启动 `asr_node`，依赖 G1 硬件 ASR → `/audio_msg` → `g1_interface` → `/g1/audio/asr`
- **使用自建 ASR**：启动 `asr_node`，它直接发布到 `/g1/audio/asr`（带 `source: "custom_asr"`）

**MVP 不支持双路并存**。如果同时运行内置 ASR 和自建 ASR，`voice_bridge` 会收到两路消息，导致重复触发 agent/stop/loco 命令。`voice_bridge` 只在 debug event 中记录 `source`，不做路由过滤（`on_asr` 直接进入 session 决策）。

如未来需要双路并存，过滤逻辑应放在 `g1_interface` 中：在 `on_audio_msg()` 桥接内置 ASR 消息之前，检查自建 ASR 是否在线（通过 liveness topic 或配置），若自建 ASR 已启用则丢弃内置 ASR 消息。这保持了 voice_bridge 的简洁性，过滤逻辑集中在桥接层。

MVP 阶段：`voice_bridge` 无需修改。

---

## 4. VAD 分段识别工作流程

### 流程

```
UDP PCM chunk (160ms/包, 5120 bytes)
    ↓
[AudioCapture 线程]  recvfrom() → pcm_queue.put(chunk)
    ↓
[处理线程]  pcm_queue.get() → SileroVAD.detect(pcm_chunk)
    ↓
 ┌─ is_speech=true ──→ [SpeechBuffer.add_speech(pcm)]
 │                         持续累积音频到录音缓冲区
 │                         超长(>15s) → 立即 flush → segment_queue
 │
 └─ is_speech=false ─→ [SpeechBuffer.add_silence(pcm)]
                          │
                          ├─ 如果之前在录音 → 静音超过阈值
                          │    → 返回 completed_segment
                          │    → segment_queue.put(segment)
                          │    → 如果段太短(<300ms) → 丢弃
    ↓
[ASR Worker 线程]  segment_queue.get() → faster-whisper.transcribe()
    ↓
构造 JSON 消息 → 发布到 /g1/audio/asr
                          │
                          └─ 如果之前不在录音 → 丢弃（噪声/静音）
```

### VAD 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `threshold` | 0.5 | Silero VAD 灵敏度（0-1，越低越灵敏） |
| `min_speech_duration_ms` | 300 | 短于此的语音段忽略，避免噪声误触发 |
| `max_silence_duration_ms` | 800 | 连续静音超此时长判定语音结束 |
| `min_audio_after_silence_ms` | 200 | 语音结束后多保留的音频（截尾保护） |
| `max_speech_duration_ms` | 15000 | 最长录音时长，超时强制截断并识别 |

### 延迟估算

```
语音结束 → VAD 检测延迟 (~160ms)
         → 音频缓冲/截尾处理 (~200ms)
         → faster-whisper medium + GPU 推理 (~500-800ms)
         → JSON 构造 + ROS2 发布 (~1ms)
         ≈ 总计 ~1-1.5 秒（从语音结束到 topic 发布）
```

加上人说话的停顿，用户体感约 2-3 秒响应，对于语音指令场景可接受。

---

## 5. 包结构

```
src/asr_node/
├── package.xml
├── setup.py                 # package_dir={"": "."} + find_packages()
├── setup.cfg
├── resource/asr_node
├── config/
│   └── asr_node.yaml        # 安装时 install 到 share/asr_node/config/
├── launch/
│   └── asr_node.launch.py
├── asr_node/                # Python 包根目录（与 voice_bridge 布局一致）
│   ├── __init__.py
│   ├── node.py              # ROS2 节点（主循环、发布）
│   ├── audio_capture.py     # UDP 组播音频接收
│   ├── asr_engine.py        # faster-whisper 封装
│   ├── vad.py               # Silero VAD 封装
│   ├── buffer.py            # 语音分段缓冲区
│   └── config.py            # AsrNodeConfig 数据类
└── tests/
    ├── test_config.py
    ├── test_audio_capture.py
    ├── test_vad.py
    ├── test_asr_engine.py
    ├── test_buffer.py
    └── test_node.py
```

布局与现有 `voice_bridge` 一致：`src/voice_bridge/voice_bridge/` 对应 `src/asr_node/asr_node/`。`setup.py` 使用 `find_packages()` + `package_dir={"": "."}` 确保包可被发现。

---

## 6. 详细设计

### 6.1 audio_capture.py — UDP 组播音频接收

```python
import socket
import struct
import threading
from typing import Callable

class AudioCapture:
    """从 G1 麦克风 UDP 组播接收 PCM 音频数据。
    
    在独立线程中运行，通过回调将 PCM chunk 传递给主处理循环。
    """

    def __init__(
        self,
        multicast_group: str = "239.168.123.161",
        multicast_port: int = 5555,
        network_prefix: str = "192.168.123.",
        recv_buffer_size: int = 8192,
    ):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(('0.0.0.0', multicast_port))
        self._sock.settimeout(2.0)  # 允许定期检查 _running 标志

        # 加入组播组
        mreq = struct.pack(
            '4s4s',
            socket.inet_aton(multicast_group),
            socket.inet_aton(self._find_interface_ip(network_prefix)),
        )
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        self._running = False
        self._thread = None
        self._callback = None

    @staticmethod
    def _find_interface_ip(prefix: str) -> str:
        """自动发现匹配网络前缀的网卡 IP。"""
        # 遍历 getifaddrs 或 netifaces，返回第一个匹配 prefix 的 IPv4 地址
        # 回退：扫描 socket 连接获取路由表
        ...
        return local_ip

    def start(self, callback: Callable[[bytes], None]) -> None:
        """启动接收线程。callback(pcm_bytes) 在每收到一个 UDP 包时调用。"""
        self._callback = callback
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        self._sock.close()

    def _recv_loop(self) -> None:
        while self._running:
            try:
                data, _ = self._sock.recvfrom(self._recv_buffer_size)
                if data and self._callback:
                    self._callback(data)
            except socket.timeout:
                continue  # 允许检查 _running
```

**关键设计决策**：

1. 独立 `daemon` 线程接收 UDP 包，不阻塞 ROS2 spin。
2. socket timeout 2s 允许线程在 `stop()` 时及时退出。
3. 通过回调接口解耦接收和处理逻辑。
4. 网络接口自动发现 `192.168.123.x`，避免硬编码。

### 6.2 vad.py — Silero VAD 封装

```python
import numpy as np

class SileroVAD:
    """基于 Silero VAD 的语音活动检测器。
    
    将 PCM chunk 转换为 16kHz float32 后进行语音检测。
    """

    def __init__(
        self,
        threshold: float = 0.5,
        sample_rate: int = 16000,
        min_speech_duration_ms: int = 300,
        max_silence_duration_ms: int = 800,
        min_audio_after_silence_ms: int = 200,
        max_speech_duration_ms: int = 15000,
    ):
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.min_speech_duration_ms = min_speech_duration_ms
        self.max_silence_duration_ms = max_silence_duration_ms
        self.min_audio_after_silence_ms = min_audio_after_silence_ms
        self.max_speech_duration_ms = max_speech_duration_ms

        # 加载 Silero VAD 模型（从 torchaudio 或本地文件）
        self._model, self._utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            trust_repo=True,
        )
        (self._get_speech_timestamps, _, _, _, _) = self._utils

    def detect(self, pcm_bytes: bytes) -> bool:
        """检测 PCM chunk 是否包含语音。
        
        Args:
            pcm_bytes: 16-bit LE PCM 数据（需为 16kHz）。
        
        Returns:
            True 表示此 chunk 包含语音。
        """
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio)
        probability = self._model(tensor, self.sample_rate).item()
        return probability > self.threshold

    def get_speech_timestamps(self, audio_float32: np.ndarray) -> dict:
        """对完整音频段进行 VAD 分段。
        
        返回 Silero 标准格式的 timestamps 列表：
        [{"start": 0, "end": 16000}, ...]
        """
        tensor = torch.from_numpy(audio_float32)
        return self._get_speech_timestamps(
            tensor, self._model,
            sampling_rate=self.sample_rate,
            threshold=self.threshold,
            min_speech_duration_ms=self.min_speech_duration_ms,
            max_silence_duration_ms=self.max_silence_duration_ms,
            min_audio_after_silence_ms=self.min_audio_after_silence_ms,
        )
```

### 6.3 buffer.py — 语音分段缓冲区

```python
import numpy as np
from dataclasses import dataclass, field

@dataclass
class SpeechSegment:
    """一段完整的语音录音。"""
    pcm_int16: bytes        # 原始 16-bit LE PCM
    sample_rate: int = 16000
    duration_ms: int = 0

class SpeechBuffer:
    """基于 VAD 状态的语音分段缓冲区。
    
    状态机：
        IDLE → (speech) → RECORDING → (silence timeout) → IDLE + return segment
                          RECORDING → (max duration) → IDLE + return segment
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        min_speech_duration_ms: int = 300,
        max_silence_duration_ms: int = 800,
        max_speech_duration_ms: int = 15000,
        padding_ms: int = 200,
    ):
        self.sample_rate = sample_rate
        # 16kHz mono 16-bit = 32000 bytes/sec = 32 bytes/ms
        self.bytes_per_second = sample_rate * 2
        self.bytes_per_ms = self.bytes_per_second // 1000
        self.max_silence_bytes = max_silence_duration_ms * self.bytes_per_ms
        self.max_speech_bytes = max_speech_duration_ms * self.bytes_per_ms
        self.padding_bytes = padding_ms * self.bytes_per_ms
        self.min_speech_bytes = min_speech_duration_ms * self.bytes_per_ms

        self._buffer = bytearray()
        self._silence_buffer = bytearray()
        self._recording = False

    def add_speech(self, pcm_bytes: bytes) -> SpeechSegment | None:
        """添加包含语音的 PCM chunk。

        Returns:
            如果语音段超长触发强制完成，返回 SpeechSegment；否则 None。
        """
        self._recording = True
        self._silence_buffer.clear()
        self._buffer.extend(pcm_bytes)

        # 超长语音强制完成（立即 flush，不再截断等待）
        if len(self._buffer) >= self.max_speech_bytes:
            return self._flush()

        return None

    def add_silence(self, pcm_bytes: bytes) -> SpeechSegment | None:
        """添加静音 PCM chunk。

        Returns:
            如果语音段完成且足够长，返回 SpeechSegment；
            如果语音段完成但太短（噪声），丢弃并返回 None；
            否则 None。
        """
        if not self._recording:
            return None

        self._silence_buffer.extend(pcm_bytes)

        # 静音超时 → 语音段完成
        if len(self._silence_buffer) >= self.max_silence_bytes:
            # 最短语音时长过滤：短于 min_speech_duration_ms 的段视为噪声
            if len(self._buffer) < self.min_speech_bytes:
                self._discard()
                return None
            # 保留 padding，丢弃多余静音
            keep = min(self.padding_bytes, len(pcm_bytes))
            self._buffer.extend(pcm_bytes[-keep:])
            return self._flush()

        return None

    def force_complete(self) -> SpeechSegment | None:
        """强制完成当前录音段（用于关闭时的清理）。
        忽略最短时长限制，确保关闭时不丢失任何已录音频。
        """
        if self._recording and self._buffer:
            return self._flush()
        return None

    def _discard(self) -> None:
        """丢弃当前缓冲区（短语音噪声过滤）。"""
        self._buffer.clear()
        self._silence_buffer.clear()
        self._recording = False

    def _flush(self) -> SpeechSegment:
        segment = SpeechSegment(
            pcm_int16=bytes(self._buffer),
            sample_rate=self.sample_rate,
            duration_ms=len(self._buffer) // self.bytes_per_ms,
        )
        self._buffer.clear()
        self._silence_buffer.clear()
        self._recording = False
        return segment
```

### 6.4 asr_engine.py — faster-whisper 封装

```python
import numpy as np
from faster_whisper import WhisperModel

class AsrEngine:
    """faster-whisper ASR 引擎封装。
    
    加载 medium 模型，GPU 推理，中文识别。
    """

    def __init__(
        self,
        model_size: str = "medium",
        device: str = "cuda",
        compute_type: str = "float16",
        language: str = "zh",
        initial_prompt: str = "",
    ):
        self.language = language
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
        self.initial_prompt = initial_prompt

    def transcribe(self, pcm_int16: bytes, sample_rate: int = 16000) -> str:
        """将 PCM 音频数据转写为文本。
        
        Args:
            pcm_int16: 16-bit LE PCM 原始数据。
            sample_rate: 采样率（必须为 16000）。
        
        Returns:
            识别出的文本字符串。如果无语音则返回空字符串。
        """
        audio = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0

        segments, info = self.model.transcribe(
            audio,
            language=self.language,
            initial_prompt=self.initial_prompt,
            beam_size=5,
            vad_filter=False,  # 已有外部 VAD，避免重复过滤
        )

        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text
```

**设计决策**：

1. `vad_filter=False`：因为我们已经有 Silero VAD 做语音分段，不需要 faster-whisper 内置的 VAD（基于 Silero 的同一模型但行为不同，可能导致截断不一致）。
2. `beam_size=5`：中等精度和速度的平衡点。
3. `initial_prompt` 热词提示提高机器人指令识别率。
4. 不设置 `confidence` 字段：faster-whisper 不提供直接的置信度分数，`no_speech_prob` 和 `avg_logprob` 的启发式转换不够可靠。输出 JSON 中不含 `confidence` 字段，`voice_bridge` 的 `parse_asr_event()` 在 `confidence` 为 `None` 时跳过阈值检查。

### 6.5 config.py — 配置数据类

```python
from dataclasses import dataclass
from typing import Any
from pathlib import Path
import yaml

DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "model": {
        "size": "medium",
        "device": "cuda",
        "compute_type": "float16",
        "language": "zh",
        "initial_prompt": (
            "以下是机器人常用指令词汇: "
            "宇树, 向前, 后退, 左转, 右转, 停止, 停下, "
            "蹲下, 站起来, 挥手, 鞠躬, 走一圈, 加速, 减速, 别动, 取消"
        ),
    },
    "vad": {
        "threshold": 0.5,
        "min_speech_duration_ms": 300,
        "max_silence_duration_ms": 800,
        "min_audio_after_silence_ms": 200,
        "max_speech_duration_ms": 15000,
    },
    "capture": {
        "multicast_group": "239.168.123.161",
        "multicast_port": 5555,
        "sample_rate": 16000,
        "recv_buffer_size": 8192,
        "network_prefix": "192.168.123.",
    },
    "topics": {
        "asr_output": "/g1/audio/asr",
    },
    "output": {
        "source": "custom_asr",
    },
}

@dataclass(frozen=True)
class AsrNodeConfig:
    model: dict[str, Any]
    vad: dict[str, Any]
    capture: dict[str, Any]
    topics: dict[str, str]
    output: dict[str, str]

    @classmethod
    def default(cls) -> "AsrNodeConfig":
        return cls._from_dict(DEFAULT_CONFIG)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AsrNodeConfig":
        with Path(path).open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        merged = _deep_merge(DEFAULT_CONFIG, loaded)
        return cls._from_dict(merged)

    @classmethod
    def _from_dict(cls, raw: dict) -> "AsrNodeConfig":
        config = cls(
            model=dict(raw["model"]),
            vad=dict(raw["vad"]),
            capture=dict(raw["capture"]),
            topics=dict(raw["topics"]),
            output=dict(raw["output"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.model["device"] not in ("cuda", "cpu"):
            raise ValueError(f"unsupported device: {self.model['device']}")
        if self.model["size"] not in ("tiny", "base", "small", "medium", "large-v3"):
            raise ValueError(f"unsupported model size: {self.model['size']}")
        if not self.topics.get("asr_output"):
            raise ValueError("missing topic config: asr_output")
        if not (0.0 < self.vad["threshold"] < 1.0):
            raise ValueError(f"vad threshold must be in (0, 1): {self.vad['threshold']}")
```

### 6.6 node.py — ROS2 节点主循环

**三线程架构**：将接收、处理、推理分离到独立线程，避免推理阻塞导致 UDP 丢包。

```text
[AudioCapture 线程]        [处理线程]              [ASR Worker 线程]
    recvfrom()                  │                        │
        ↓                       ↓                        ↓
    pcm_queue.put(chunk)    pcm_queue.get(chunk)     segment_queue.get(seg)
                              ↓                        ↓
                         VAD.detect()           engine.transcribe()
                              ↓                        ↓
                         SpeechBuffer           构造 JSON 消息
                         add_speech/add_silence      ↓
                              ↓                   _asr_pub.publish()
                         segment_queue.put()    (rclpy 线程安全)
```

```python
import json
import os
import queue
import threading
import rclpy
from std_msgs.msg import String

from asr_node.config import AsrNodeConfig
from asr_node.audio_capture import AudioCapture
from asr_node.vad import SileroVAD
from asr_node.buffer import SpeechBuffer, SpeechSegment
from asr_node.asr_engine import AsrEngine

# 队列容量上限：16kHz/16bit/mono 约 32KB/s，
# 100 个 160ms chunk ≈ 16 秒音频，足够覆盖 ASR 推理延迟
PCM_QUEUE_SIZE = 100
SEGMENT_QUEUE_SIZE = 10
_STOP_SENTINEL = None  # 队列终止标记


class AsrNode:
    """自建 ASR 节点。

    三线程架构：
    1. AudioCapture 线程：UDP recvfrom → pcm_queue（轻量，不阻塞）
    2. 处理线程：VAD + SpeechBuffer → segment_queue（CPU 轻量）
    3. ASR Worker 线程：faster-whisper 推理 → ROS2 publish（GPU 密集）
    """

    def __init__(self, node: rclpy.node.Node, config: AsrNodeConfig):
        self.node = node
        self.config = config
        self._msg_counter = 0
        self._lock = threading.Lock()

        # 队列
        self._pcm_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=PCM_QUEUE_SIZE)
        self._segment_queue: queue.Queue[SpeechSegment | None] = queue.Queue(maxsize=SEGMENT_QUEUE_SIZE)

        # 初始化组件
        self._engine = AsrEngine(
            model_size=config.model["size"],
            device=config.model["device"],
            compute_type=config.model["compute_type"],
            language=config.model["language"],
            initial_prompt=config.model.get("initial_prompt", ""),
        )
        self._vad = SileroVAD(
            threshold=config.vad["threshold"],
            sample_rate=config.capture["sample_rate"],
            min_speech_duration_ms=config.vad["min_speech_duration_ms"],
            max_silence_duration_ms=config.vad["max_silence_duration_ms"],
            min_audio_after_silence_ms=config.vad["min_audio_after_silence_ms"],
            max_speech_duration_ms=config.vad["max_speech_duration_ms"],
        )
        self._buffer = SpeechBuffer(
            sample_rate=config.capture["sample_rate"],
            min_speech_duration_ms=config.vad["min_speech_duration_ms"],
            max_silence_duration_ms=config.vad["max_silence_duration_ms"],
            max_speech_duration_ms=config.vad["max_speech_duration_ms"],
            padding_ms=config.vad["min_audio_after_silence_ms"],
        )
        self._capture = AudioCapture(
            multicast_group=config.capture["multicast_group"],
            multicast_port=config.capture["multicast_port"],
            network_prefix=config.capture["network_prefix"],
            recv_buffer_size=config.capture["recv_buffer_size"],
        )

        # ROS2 接口
        self._asr_pub = node.create_publisher(
            String, config.topics["asr_output"], 10
        )

        # 模型加载日志
        node.get_logger().info(
            f"ASR engine loaded: model={config.model['size']}, "
            f"device={config.model['device']}, "
            f"language={config.model['language']}"
        )
        node.get_logger().info(
            f"VAD configured: threshold={config.vad['threshold']}, "
            f"max_silence={config.vad['max_silence_duration_ms']}ms"
        )

    def start(self) -> None:
        """启动所有线程。"""
        # AudioCapture 线程：只做 recvfrom + 入队
        self._capture.start(self._pcm_queue.put)
        # 处理线程：VAD + SpeechBuffer
        self._process_thread = threading.Thread(
            target=self._process_loop, daemon=True, name="asr_process"
        )
        self._process_thread.start()
        # ASR Worker 线程：推理 + 发布
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="asr_worker"
        )
        self._worker_thread.start()

        self.node.get_logger().info(
            f"Audio capture started: "
            f"{self.config.capture['multicast_group']}:{self.config.capture['multicast_port']}"
        )

    def stop(self) -> None:
        """停止所有线程。按顺序：接收 → 处理 → Worker。"""
        self._capture.stop()
        # 发送终止标记到 pcm_queue
        self._pcm_queue.put(_STOP_SENTINEL)
        self._process_thread.join(timeout=5.0)
        # 发送终止标记到 segment_queue
        self._segment_queue.put(_STOP_SENTINEL)
        self._worker_thread.join(timeout=10.0)  # 等待可能正在进行的推理

    def _process_loop(self) -> None:
        """处理线程：从 pcm_queue 取 chunk，运行 VAD，管理 SpeechBuffer。"""
        while True:
            pcm_bytes = self._pcm_queue.get()
            if pcm_bytes is _STOP_SENTINEL:
                # 关闭：flush 残余语音段
                segment = self._buffer.force_complete()
                if segment:
                    try:
                        self._segment_queue.put(segment, timeout=2.0)
                    except queue.Full:
                        self.node.get_logger().warning(
                            "segment queue full during shutdown, dropping residual audio"
                        )
                self._segment_queue.put(_STOP_SENTINEL)
                return

            is_speech = self._vad.detect(pcm_bytes)

            if is_speech:
                segment = self._buffer.add_speech(pcm_bytes)
            else:
                segment = self._buffer.add_silence(pcm_bytes)

            if segment is not None:
                try:
                    self._segment_queue.put(segment, timeout=2.0)
                except queue.Full:
                    self.node.get_logger().warning(
                        "segment queue full, dropping speech segment"
                    )

    def _worker_loop(self) -> None:
        """ASR Worker 线程：从 segment_queue 取语音段，推理并发布。"""
        while True:
            segment = self._segment_queue.get()
            if segment is _STOP_SENTINEL:
                return
            self._transcribe_and_publish(segment)

    def _transcribe_and_publish(self, segment: SpeechSegment) -> None:
        """识别语音段并发布结果。"""
        try:
            text = self._engine.transcribe(
                segment.pcm_int16, segment.sample_rate
            )
        except Exception as exc:
            self.node.get_logger().warning(
                f"ASR transcription failed: {exc}"
            )
            return

        if not text.strip():
            self.node.get_logger().debug(
                "ASR returned empty text, skipping publish"
            )
            return

        with self._lock:
            self._msg_counter += 1
            index = self._msg_counter

        payload = json.dumps({
            "text": text,
            "is_final": True,
            "source": self.config.output["source"],
            "language": self.config.model["language"],
            "index": index,
        }, ensure_ascii=False)

        msg = String()
        msg.data = payload
        self._asr_pub.publish(msg)

        self.node.get_logger().info(
            f"ASR result [{index}]: {text}"
        )


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("asr_node")
    node.declare_parameter("config_path", "")
    config_path = node.get_parameter("config_path").get_parameter_value().string_value

    if not config_path:
        try:
            from ament_index_python.packages import get_package_share_directory
            config_dir = get_package_share_directory("asr_node")
            config_path = os.path.join(config_dir, "config", "asr_node.yaml")
        except Exception:
            pass  # fallback to default config

    config = AsrNodeConfig.from_yaml(config_path) if config_path else AsrNodeConfig.default()

    asr_node = AsrNode(node=node, config=config)
    asr_node.start()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        asr_node.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
```

**线程安全说明**：

- **AudioCapture 线程**：只做 `recvfrom()` + `pcm_queue.put()`，不做任何计算。`put()` 在队列满时阻塞（back-pressure），避免无限内存增长。不会因推理阻塞丢包。
- **处理线程**：从 `pcm_queue.get()` 取 chunk，运行轻量 VAD 检测（~1ms/chunk），管理 SpeechBuffer 状态机。完成的语音段放入 `segment_queue`。
- **ASR Worker 线程**：从 `segment_queue.get()` 取语音段，运行 faster-whisper 推理（~0.5-1.5s/段）。推理期间不阻塞其他线程。`publish()` 是线程安全的（`rclpy` 内部使用 mutex）。
- **终止顺序**：`stop()` 先停 AudioCapture（不再接收），然后发 `_STOP_SENTINEL` 到 `pcm_queue` 让处理线程 flush 残余音频后退出的 `segment_queue` 发终止标记让 Worker 线程退出。
- `_msg_counter` 通过 `_lock` 保护。
- 队列有界（`PCM_QUEUE_SIZE=100`, `SEGMENT_QUEUE_SIZE=10`），防止内存无限增长。满时 `put(timeout=2.0)` 丢弃并 warning。

### 6.7 配置文件 — asr_node.yaml

```yaml
# asr_node 配置
# faster-whisper 模型参数
model:
  size: "medium"               # tiny/base/small/medium/large-v3
  device: "cuda"               # cuda / cpu
  compute_type: "float16"      # float16 (GPU) / int8 (CPU)
  language: "zh"               # 主要识别语言
  initial_prompt: >-
    以下是机器人常用指令词汇:
    宇树, 向前, 后退, 左转, 右转, 停止, 停下,
    蹲下, 站起来, 挥手, 鞠躬, 走一圈, 加速, 减速, 别动, 取消

# Silero VAD 参数
vad:
  threshold: 0.5
  min_speech_duration_ms: 300
  max_silence_duration_ms: 800
  min_audio_after_silence_ms: 200
  max_speech_duration_ms: 15000

# UDP 组播音频接收参数
capture:
  multicast_group: "239.168.123.161"
  multicast_port: 5555
  sample_rate: 16000
  recv_buffer_size: 8192
  network_prefix: "192.168.123."

# ROS2 话题
topics:
  asr_output: "/g1/audio/asr"    # 发布到 voice_bridge 消费的 topic

# 输出格式
output:
  source: "custom_asr"           # 标记来源，区分内置 ASR
```

### 6.8 输出消息格式

发布到 `/g1/audio/asr` 的 JSON：

```json
{
  "text": "宇树，向前走一秒",
  "is_final": true,
  "source": "custom_asr",
  "language": "zh",
  "index": 42
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | string | 识别出的文本 |
| `is_final` | bool | 始终为 `true`（VAD 分段后的最终结果） |
| `source` | string | `"custom_asr"`，区分内置 ASR（无此字段） |
| `language` | string | 识别语言 |
| `index` | int | 节点内递增计数器，用于日志追踪 |

**不包含 `confidence` 字段**。`voice_bridge` 的 `parse_asr_event()`（`intent.py`）在 `confidence` 为 `None` 时跳过 `min_confidence` 检查，不影响现有行为。

---

## 7. 与现有系统的兼容性

### voice_bridge

无需修改。`parse_asr_event()` 已支持：
- JSON 格式中的 `source` 字段
- `confidence` 为 `None` 时跳过阈值检查
- `is_final` 字段

### g1_interface

无需修改。自建 ASR 绕过 `g1_interface` 的 `/audio_msg` 桥接，直接发布到 `/g1/audio/asr`。

### g1_sim

MVP 不做修改。后续可考虑在 `g1_sim` 中添加模拟 UDP 音频流的功能，用于无硬件环境的端到端测试。

### 与内置 ASR 并存

**MVP 不支持双路并存**。同时运行内置 ASR 和自建 ASR 会导致 `voice_bridge` 收到重复消息，触发重复命令。

二选一运行：
- **内置 ASR**：不启动 `asr_node`
- **自建 ASR**：启动 `asr_node`，确保硬件端 ASR 不会同时向 `/audio_msg` 发布文本（可通过 G1 API 抑制）

如需双路并存，应在 `g1_interface.on_audio_msg()` 中添加 source 过滤：当检测到自建 ASR 活跃时，跳过内置 ASR 的桥接。

---

## 8. 依赖

### Python 依赖

```
faster-whisper>=1.0.0
torch>=2.0
torchaudio
numpy
pyyaml
```

### 系统依赖

- CUDA Toolkit（GPU 推理）
- ROS2 Humble + `rclpy`
- `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`

### 安装

```bash
pip install faster-whisper
# torch + torchaudio 需匹配 CUDA 版本，参考：
# https://pytorch.org/get-started/locally/
```

---

## 9. 启动方式

### 启动节点

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
colcon build --packages-select asr_node
source install/setup.bash
ros2 run asr_node asr_node --ros-args -p config_path:=src/asr_node/config/asr_node.yaml
```

### ROS2 Launch

```python
# launch/asr_node.launch.py
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    config_dir = os.path.join(get_package_share_directory('asr_node'), 'config')
    return LaunchDescription([
        Node(
            package='asr_node',
            executable='asr_node',
            name='asr_node',
            output='screen',
            parameters=[{
                'config_path': os.path.join(config_dir, 'asr_node.yaml'),
            }],
        ),
    ])
```

### 验证

```bash
# 监听 ASR 输出
ros2 topic echo /g1/audio/asr

# 期望输出：
# data: "{\"text\":\"向前走\",\"is_final\":true,\"source\":\"custom_asr\",\"language\":\"zh\",\"index\":1}"
```

---

## 10. 边界情况处理

### 10.1 无语音（纯静音）

VAD 持续返回 `is_speech=false`，`SpeechBuffer` 处于 `IDLE` 状态，不累积音频，不触发识别。无 ROS 消息发布。

### 10.2 短语音（<300ms）

`min_speech_duration_ms=300` 在 `SpeechBuffer` 状态机中过滤噪声误触发。短于 300ms 的语音段通过 VAD 检测后会在 `SpeechBuffer` 中累积，但当静音超时触发 flush 时，`add_silence()` 检查 `_buffer` 长度不足 `min_speech_bytes`，调用 `_discard()` 丢弃。不会发布任何消息。

### 10.3 长语音（>15s）

`max_speech_duration_ms=15000` 强制完成。超过 15 秒的语音段在 `SpeechBuffer.add_speech()` 中达到 `max_speech_bytes` 时立即 `_flush()`，返回 `SpeechSegment` 触发识别并发布。用户可以在说完前得到部分结果。`_on_audio_chunk` 检查返回值并提交给 ASR worker。

### 10.4 连续说话（中间停顿 <800ms）

`max_silence_duration_ms=800` 决定了"句子间隔"的判定。如果说话中停顿少于 800ms（正常语速的句间停顿），不会触发分段，整段语音作为一个 segment 识别。

### 10.5 UDP 包丢失

UDP 组播不保证可靠传输。偶尔丢包会导致 PCM 数据中出现短暂的静音或爆音，对 VAD 和 ASR 影响较小（faster-whisper 有一定的容错能力）。严重丢包会导致识别质量下降，但不会导致节点崩溃。

### 10.6 识别结果为空

`_transcribe_and_publish` 检查 `text.strip()`，空文本不发布。可能原因：纯噪声被误判为语音段、背景音乐等。

### 10.7 网络接口不可用

`AudioCapture._find_interface_ip()` 找不到 `192.168.123.x` 的网卡时，应抛出 `RuntimeError` 并在日志中明确提示。节点启动失败，不进行 ASR 推理。

### 10.8 GPU 不可用

如果配置为 `device: "cuda"` 但 CUDA 不可用（驱动缺失、无 GPU），faster-whisper 初始化时会抛出异常。节点启动失败。可通过配置切换为 `device: "cpu"` 降级运行（推理速度较慢）。

---

## 11. 性能考虑

### GPU 显存

| 组件 | 预估显存 |
|------|----------|
| faster-whisper medium (float16) | ~2.5GB |
| Silero VAD | ~50MB |
| CUDA runtime | ~500MB |
| **总计** | **~3GB** |

消费级 GPU（8-12GB）充裕。

### CPU 占用

- UDP 接收线程：极低（`recvfrom` 阻塞）
- VAD 推理：极低（Silero VAD 模型很小）
- faster-whisper 推理：GPU 承担主要计算，CPU 仅做数据传递
- numpy PCM 转换：可忽略

### 推理延迟

| 音频时长 | medium + GPU 推理 |
|----------|-------------------|
| 1s | ~0.2s |
| 3s | ~0.5s |
| 5s | ~0.8s |
| 10s | ~1.5s |

典型语音指令（2-5 秒），端到端延迟约 1-2 秒。

---

## 12. 测试策略

### 单元测试

- **test_config.py**：配置加载、验证、默认值、YAML 覆盖
- **test_vad.py**：VAD 检测（纯语音、纯静音、混合）— 使用预录 PCM 文件
- **test_buffer.py**：SpeechBuffer 状态机（IDLE→RECORDING→完成、超时、短语音）
- **test_asr_engine.py**：转录（使用预录 PCM 文件，检查输出非空且为字符串）— 标记为 GPU 测试，CI 中可跳过

### 集成测试

- **test_audio_capture.py**：模拟 UDP 组播发送 PCM 数据，验证接收回调（使用 `socket` 发送）
- **test_node.py**：模拟 UDP 发送 + 验证 ROS topic 发布（需要 ROS2 环境）

### 手工验证

```bash
# 终端 1：启动 asr_node
ros2 run asr_node asr_node

# 终端 2：监听 ASR 输出
ros2 topic echo /g1/audio/asr

# 终端 3：对着机器人麦克风说话，观察终端 2 输出
```

### GPU 测试标记

```python
import pytest

GPU_AVAILABLE = pytest.mark.skipif(
    not _has_cuda(),
    reason="CUDA GPU not available"
)

@GPU_AVAILABLE
def test_asr_engine_transcribe():
    ...
```

---

## 13. 未来扩展（MVP 不做）

1. **唤醒词检测**：在 VAD 之前或之后添加唤醒词检测（如 Porcupine、OpenWakeWord），避免持续识别。
2. **多语言自动切换**：faster-whisper 支持 `language=None` 自动检测，但延迟更高。
3. **流式识别**：每 1-2 秒推理一次，逐步产出结果，降低首字延迟。
4. **ASR 结果缓存和去重**：避免短时间内重复发布相似结果。
5. **g1_sim 模拟音频流**：在模拟器中添加模拟 UDP 组播 PCM 流，用于无硬件环境的端到端测试。
6. **性能监控 topic**：发布推理延迟、GPU 利用率等指标。
7. **多模型热切换**：运行时切换 tiny/medium/large 模型以平衡速度和精度。
8. **推理线程池**：将推理从 AudioCapture 线程中分离，避免 UDP 包排队。

---

## 14. 风险和缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| UDP 组播不通（网络配置） | 无法接收音频 | 启动时检测网络接口，明确错误提示 |
| GPU 不可用 | 无法启动 ASR | 配置降级为 `device: "cpu"`，日志提示 |
| faster-whisper 识别延迟高 | 语音指令响应慢 | MVP 用 medium 模型平衡；后续可换 small |
| Silero VAD 误触发噪声 | 频繁空识别 | `min_speech_duration_ms=300` 过滤 |
| 与内置 ASR 消息冲突 | voice_bridge 收到双路 ASR | `source: "custom_asr"` 标记区分 |
| 中文识别质量不够 | 指令识别错误 | `initial_prompt` 热词提示；后续可换 large-v3 |

---

## 15. 验收标准

### 功能验收

- [ ] 节点启动后从 UDP 组播接收 PCM 音频
- [ ] VAD 正确检测语音段和静音段
- [ ] 语音段结束后 faster-whisper 识别出文本
- [ ] 识别结果以 JSON 格式发布到 `/g1/audio/asr`
- [ ] JSON 包含 `text`, `is_final`, `source`, `language`, `index` 字段
- [ ] JSON 不包含 `confidence` 字段
- [ ] `source` 字段值为 `"custom_asr"`
- [ ] `index` 字段递增
- [ ] 空识别结果不发布
- [ ] 超长语音 (>15s) 被截断并识别
- [ ] 网络接口不可用时启动失败并有明确错误提示

### 集成验收

- [ ] voice_bridge 消费自建 ASR 消息，行为与内置 ASR 一致
- [ ] wake word / stop word / agent 路由正常工作
- [ ] 内置 ASR 和自建 ASR 可以同时运行
- [ ] 不启动 asr_node 时，系统回退到内置 ASR，无影响

### 配置验收

- [ ] YAML 配置可覆盖默认值
- [ ] 模型大小、设备、语言、VAD 参数均可配置
- [ ] 网络接口前缀可配置

### 测试验收

- [ ] 单元测试覆盖 config、vad、buffer、asr_engine
- [ ] GPU 测试有 skipif 标记
- [ ] 集成测试覆盖 UDP → VAD → ASR → ROS2 publish 全链路
- [ ] 所有测试通过

### 文档验收

- [ ] 设计文档完整
- [ ] README 包含安装、配置、启动说明
- [ ] 代码注释充分

---

## 16. 参考资料

- SDK2 音频客户端示例：`.unitree/unitree_sdk2/example/g1/audio/g1_audio_client_example.cpp`
- SDK2 AudioClient 头文件：`.unitree/unitree_sdk2/include/unitree/robot/g1/audio/g1_audio_client.hpp`
- faster-whisper 文档：https://github.com/SYSTRAN/faster-whisper
- Silero VAD 文档：https://github.com/snakers4/silero-vad
- voice_bridge intent 解析：`src/voice_bridge/voice_bridge/intent.py`
- g1_interface ASR 桥接：`src/g1_interface/g1_interface/node.py` (on_audio_msg)
- 数据契约：`docs/data_contracts.md` (`/g1/audio/asr` 章节)
- 现有 ASR 模拟设计：`docs/superpowers/specs/2025-01-06-asr-message-simulation-design.md`
