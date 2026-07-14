# asr_node

Custom ASR node for Unitree G1 - receives microphone audio from UDP multicast,
runs faster-whisper speech recognition, and publishes typed
`g1_agent_msgs/msg/VoiceEvent` messages to `/g1/audio/asr`.

## Architecture

Three-thread pipeline:

```text
[AudioCapture] UDP recvfrom -> pcm_queue
[Processor]    VAD + SpeechBuffer -> segment_queue
[ASR Worker]   faster-whisper -> /g1/audio/asr
```

## Development Environment

```bash
make bootstrap-asr
make build
make test
```

The workspace uses the root `.venv-ros` Python 3.10 uv environment. Default
CI runs unit tests without loading ASR models or initializing CUDA.

## Launch

```bash
ros2 launch asr_node asr_node.launch.py
```

## Verify

```bash
ros2 topic echo /g1/audio/asr
```

Expected output:

```text
source: custom_asr
event_type: asr
has_sequence_id: true
sequence_id: 1
text: 向前走
is_final: true
language: zh
```

## Configuration

Edit `src/asr_node/config/asr_node.yaml` before building. Key settings:

- `model.size`: `tiny`/`base`/`small`/`medium`/`large-v3` (default: `medium`)
- `model.device`: `cuda` or `cpu` (default: `cuda`)
- `vad.threshold`: 0.0-1.0 (default: 0.5)
- `capture.network_prefix`: network interface filter (default: `192.168.123.`)

GPU-dependent tests for VAD and ASR engine are skipped in the default local test
environment.
