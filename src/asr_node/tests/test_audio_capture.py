"""Tests for asr_node.audio_capture - UDP multicast receiver."""
import socket
import threading
import time

from asr_node.audio_capture import AudioCapture


def _send_udp(data: bytes, port: int = 15555) -> None:
    """Send a UDP packet to localhost on the given port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(data, ("127.0.0.1", port))
    sock.close()


def test_start_and_stop():
    """AudioCapture can be started and stopped without error."""
    cap = AudioCapture(
        multicast_group="239.0.0.1",
        multicast_port=15555,
        network_prefix="127.0.0.",
        recv_buffer_size=1024,
    )
    cap.start(lambda d: None)
    cap.stop()


def test_stop_is_idempotent():
    cap = AudioCapture(
        multicast_group="239.0.0.1",
        multicast_port=15556,
        network_prefix="127.0.0.",
        recv_buffer_size=1024,
    )
    cap.start(lambda d: None)
    cap.stop()
    cap.stop()


def test_recv_callback_called():
    """Callback is called when a UDP packet is received."""
    received = []
    event = threading.Event()

    cap = AudioCapture(
        multicast_group="239.0.0.1",
        multicast_port=15557,
        network_prefix="127.0.0.",
        recv_buffer_size=1024,
    )
    cap.start(lambda d: (received.append(d), event.set()))

    time.sleep(0.1)
    _send_udp(b"\x00\x01" * 100, port=15557)
    event.wait(timeout=2.0)
    cap.stop()

    assert len(received) == 1
    assert len(received[0]) == 200


def test_stop_thread_exits():
    """Thread exits after stop() without hanging."""
    cap = AudioCapture(
        multicast_group="239.0.0.1",
        multicast_port=15558,
        network_prefix="127.0.0.",
        recv_buffer_size=1024,
    )
    cap.start(lambda d: None)
    time.sleep(0.1)
    cap.stop()
    assert not cap._thread.is_alive()
