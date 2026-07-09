# asr_node

Custom ASR node for Unitree G1 - receives microphone audio from UDP multicast,
runs faster-whisper speech recognition, and publishes recognized text to
`/g1/audio/asr`.

## Architecture

Three-thread pipeline:

```text
[AudioCapture] UDP recvfrom -> pcm_queue
[Processor]    VAD + SpeechBuffer -> segment_queue
[ASR Worker]   faster-whisper -> /g1/audio/asr
```

## Dependencies

```bash
pip install numpy
pip install faster-whisper
# torch + torchaudio must match your CUDA version
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

## Build

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select asr_node
source install/setup.bash
```

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
data: "{\"text\":\"向前走\",\"is_final\":true,\"source\":\"custom_asr\",\"language\":\"zh\",\"index\":1}"
```

## Configuration

Edit `src/asr_node/config/asr_node.yaml` before building. Key settings:

- `model.size`: `tiny`/`base`/`small`/`medium`/`large-v3` (default: `medium`)
- `model.device`: `cuda` or `cpu` (default: `cuda`)
- `vad.threshold`: 0.0-1.0 (default: 0.5)
- `capture.network_prefix`: network interface filter (default: `192.168.123.`)

## Unit Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node:${PYTHONPATH:-} .venv/bin/python -m pytest src/asr_node/tests -q
```

GPU-dependent tests for VAD and ASR engine are skipped in the default local test
environment.
