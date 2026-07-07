from __future__ import annotations

import argparse
import asyncio
import queue
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi.staticfiles import StaticFiles

from voice_bridge_debug.config import DebugPanelConfig
from voice_bridge_debug.ros_node import DebugBridgeNode
from voice_bridge_debug.routes import create_app
from voice_bridge_debug.state import PanelState
from voice_bridge_debug.ws import WebSocketManager


class DebugBridgeServer:
    def __init__(self, config: DebugPanelConfig, *, prod: bool = False):
        static_dir = Path(__file__).with_name("frontend_dist")
        if prod and not static_dir.exists():
            raise FileNotFoundError(f"frontend static directory not found: {static_dir}")

        import rclpy

        self.rclpy = rclpy
        if not rclpy.ok():
            rclpy.init()
        self.config = config
        self.prod = prod
        self.loop: asyncio.AbstractEventLoop | None = None
        self.web_broadcast_queue: asyncio.Queue | None = None
        self.asr_publish_queue: queue.Queue = queue.Queue()
        self.ws_manager = WebSocketManager()
        self.state = PanelState(max_events=int(config.timeline["max_events"]), notify_web=self.notify_web_from_ros_thread)
        self.node = rclpy.create_node("voice_bridge_debug_node")
        self.ros_node = DebugBridgeNode(
            self.node,
            config,
            self.state,
            self.asr_publish_queue,
            self.notify_web_from_ros_thread,
        )
        self._spin_thread: threading.Thread | None = None
        self._broadcast_task: asyncio.Task | None = None
        self.app = create_app(self)
        if prod:
            self.app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    async def startup(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.web_broadcast_queue = asyncio.Queue()
        self._broadcast_task = asyncio.create_task(self.broadcast_worker())
        self._spin_thread = threading.Thread(target=self.rclpy.spin, args=(self.node,), daemon=True)
        self._spin_thread.start()

    def notify_web_from_ros_thread(self, message: dict[str, Any]) -> None:
        if self.loop is None or self.web_broadcast_queue is None:
            return
        self.loop.call_soon_threadsafe(self.web_broadcast_queue.put_nowait, message)

    async def broadcast_worker(self) -> None:
        assert self.web_broadcast_queue is not None
        while True:
            message = await self.web_broadcast_queue.get()
            await self.ws_manager.broadcast(message)

    async def shutdown(self) -> None:
        if self._broadcast_task is not None:
            self._broadcast_task.cancel()
        self.node.destroy_node()
        if self.rclpy.ok():
            self.rclpy.shutdown()

    def run(self) -> None:
        if self.config.server["allow_remote"]:
            print("WARNING: debug panel remote access enabled; ASR publishing may trigger robot command chains.")
        uvicorn.run(self.app, host=self.config.server["host"], port=int(self.config.server["port"]))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="")
    parser.add_argument("--prod", action="store_true")
    args = parser.parse_args(argv)
    config = DebugPanelConfig.from_yaml(args.config) if args.config else DebugPanelConfig.default()
    DebugBridgeServer(config, prod=args.prod).run()
