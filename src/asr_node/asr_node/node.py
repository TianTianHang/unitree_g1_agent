"""ASR node - ROS2 node with a three-thread speech recognition pipeline."""
from __future__ import annotations

import os
import queue
import threading

from asr_node.asr_engine import AsrEngine
from asr_node.audio_capture import AudioCapture
from asr_node.buffer import SpeechBuffer, SpeechSegment
from asr_node.config import AsrNodeConfig
from asr_node.vad import SileroVAD

PCM_QUEUE_SIZE = 100
SEGMENT_QUEUE_SIZE = 10
_STOP_SENTINEL = None


def _load_ros_messages():
    from g1_agent_msgs.msg import VoiceEvent

    return {"VoiceEvent": VoiceEvent}


class AsrNode:
    """Custom ASR node with UDP capture, VAD segmentation, and ASR worker."""

    def __init__(self, node, config: AsrNodeConfig) -> None:
        self.node = node
        self.config = config
        self.msg = _load_ros_messages()
        self._msg_counter = 0
        self._lock = threading.Lock()

        self._pcm_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=PCM_QUEUE_SIZE)
        self._segment_queue: queue.Queue[SpeechSegment | None] = queue.Queue(
            maxsize=SEGMENT_QUEUE_SIZE
        )

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

        self._asr_pub = node.create_publisher(
            self.msg["VoiceEvent"],
            config.topics["asr_output"],
            10,
        )

        node.get_logger().info(
            f"ASR engine loaded: model={config.model['size']}, "
            f"device={config.model['device']}, "
            f"language={config.model['language']}"
        )

    def start(self) -> None:
        """Start capture, processing, and ASR worker threads."""
        self._capture.start(self._enqueue_pcm)
        self._process_thread = threading.Thread(
            target=self._process_loop,
            daemon=True,
            name="asr_process",
        )
        self._process_thread.start()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="asr_worker",
        )
        self._worker_thread.start()

        self.node.get_logger().info(
            f"Audio capture started: "
            f"{self.config.capture['multicast_group']}:"
            f"{self.config.capture['multicast_port']}"
        )

    def stop(self) -> None:
        """Stop all threads in capture -> process -> worker order."""
        self._capture.stop()
        try:
            self._pcm_queue.put(_STOP_SENTINEL, timeout=1.0)
        except queue.Full:
            self.node.get_logger().warning(
                "pcm queue full during shutdown, process thread may not stop cleanly"
            )
        if hasattr(self, "_process_thread"):
            self._process_thread.join(timeout=5.0)
        if hasattr(self, "_worker_thread"):
            self._worker_thread.join(timeout=10.0)

    def _enqueue_pcm(self, pcm_bytes: bytes) -> None:
        try:
            self._pcm_queue.put(pcm_bytes, timeout=0.2)
        except queue.Full:
            self.node.get_logger().warning("pcm queue full, dropping audio chunk")

    def _process_loop(self) -> None:
        """Processing thread: VAD + SpeechBuffer state machine."""
        while True:
            pcm_bytes = self._pcm_queue.get()
            if pcm_bytes is None:
                segment = self._buffer.force_complete()
                if segment:
                    try:
                        self._segment_queue.put(segment, timeout=2.0)
                    except queue.Full:
                        self.node.get_logger().warning(
                            "segment queue full during shutdown, dropping residual audio"
                        )
                try:
                    self._segment_queue.put(_STOP_SENTINEL, timeout=2.0)
                except queue.Full:
                    self.node.get_logger().warning(
                        "segment queue full during shutdown, worker may not stop cleanly"
                    )
                return

            try:
                is_speech = self._vad.detect(pcm_bytes)
            except Exception as exc:
                self.node.get_logger().warning(f"VAD detection failed: {exc}")
                is_speech = False
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
        """ASR worker thread: transcribe speech segments and publish results."""
        while True:
            segment = self._segment_queue.get()
            if segment is None:
                return
            self._transcribe_and_publish(segment)

    def _transcribe_and_publish(self, segment: SpeechSegment) -> None:
        """Run ASR inference and publish result to the configured ROS topic."""
        try:
            text = self._engine.transcribe(segment.pcm_int16, segment.sample_rate)
        except Exception as exc:
            self.node.get_logger().warning(f"ASR transcription failed: {exc}")
            return

        if not text.strip():
            self.node.get_logger().debug("ASR returned empty text, skipping publish")
            return

        with self._lock:
            self._msg_counter += 1
            index = self._msg_counter

        self._asr_pub.publish(self._build_voice_event(text, index))

        self.node.get_logger().info(f"ASR result [{index}]: {text}")

    def _build_voice_event(self, text: str, sequence_id: int):
        msg = self.msg["VoiceEvent"]()
        msg.stamp = self.node.get_clock().now().to_msg()
        msg.source = str(self.config.output["source"])
        msg.event_type = str(getattr(self.msg["VoiceEvent"], "EVENT_ASR"))
        msg.has_sequence_id = True
        msg.sequence_id = sequence_id
        msg.text = text
        msg.has_confidence = False
        msg.confidence = 0.0
        msg.is_final = True
        msg.language = str(self.config.model["language"])
        msg.has_playback_state = False
        return msg


def main(args=None) -> None:
    import rclpy

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
            pass

    config = (
        AsrNodeConfig.from_yaml(config_path)
        if config_path
        else AsrNodeConfig.default()
    )

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
