"""Audio capture - receive G1 microphone PCM from UDP multicast."""
from __future__ import annotations

import socket
import struct
import threading
from typing import Callable


class AudioCapture:
    """Receives PCM audio from G1 microphone UDP multicast."""

    def __init__(
        self,
        multicast_group: str = "239.168.123.161",
        multicast_port: int = 5555,
        network_prefix: str = "192.168.123.",
        recv_buffer_size: int = 8192,
    ) -> None:
        self._multicast_group = multicast_group
        self._recv_buffer_size = recv_buffer_size

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", multicast_port))
        self._sock.settimeout(2.0)

        local_ip = self._find_interface_ip(network_prefix)
        mreq = struct.pack(
            "4s4s",
            socket.inet_aton(multicast_group),
            socket.inet_aton(local_ip),
        )
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        self._running = False
        self._thread: threading.Thread | None = None

    @staticmethod
    def _find_interface_ip(prefix: str) -> str:
        """Find the first IPv4 address matching the given network prefix."""
        if "127.0.0.1".startswith(prefix):
            return "127.0.0.1"

        candidates = set()
        try:
            hostname = socket.gethostname()
            for addr_info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                candidates.add(addr_info[4][0])
        except OSError:
            pass

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            candidates.add(sock.getsockname()[0])
            sock.close()
        except OSError:
            pass

        for ip in sorted(candidates):
            if ip.startswith(prefix):
                return ip

        raise RuntimeError(f"no network interface found with prefix '{prefix}'")

    def start(self, callback: Callable[[bytes], None]) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._recv_loop,
            args=(callback,),
            daemon=True,
            name="asr_audio_capture",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        try:
            self._sock.close()
        except OSError:
            pass

    def _recv_loop(self, callback: Callable[[bytes], None]) -> None:
        while self._running:
            try:
                data, _ = self._sock.recvfrom(self._recv_buffer_size)
                if data:
                    callback(data)
            except socket.timeout:
                continue
            except OSError:
                break
