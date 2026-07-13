from __future__ import annotations

import sys
import types


class String:
    def __init__(self):
        self.data = ""


class DiagnosticArray:
    def __init__(self):
        self.status = []


class DiagnosticStatus:
    def __init__(self):
        self.name = ""
        self.level = b"\x00"
        self.message = ""
        self.values = []


class KeyValue:
    def __init__(self):
        self.key = ""
        self.value = ""


class Imu:
    def __init__(self):
        self.header = types.SimpleNamespace(frame_id="")
        self.orientation = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
        self.angular_velocity = types.SimpleNamespace(x=0.0, y=0.0, z=0.0)
        self.linear_acceleration = types.SimpleNamespace(x=0.0, y=0.0, z=0.0)


class ClockType:
    STEADY_TIME = "steady_time"


class Clock:
    def __init__(self, clock_type=None):
        self.clock_type = clock_type


class Request:
    def __init__(self):
        self.header = types.SimpleNamespace(identity=types.SimpleNamespace(id=0, api_id=0))
        self.parameter = ""


class Response:
    def __init__(self):
        self.header = types.SimpleNamespace(identity=types.SimpleNamespace(id=0, api_id=0))
        self.status = types.SimpleNamespace(code=0)
        self.data = ""


class IMUState:
    pass


class LowState:
    pass


def _install_module(name: str, attributes: dict[str, object]) -> None:
    package_name, _, child_name = name.partition(".")
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        sys.modules[package_name] = package
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    setattr(package, child_name, module)
    sys.modules[name] = module


def pytest_configure():
    _install_module(
        "diagnostic_msgs.msg",
        {
            "DiagnosticArray": DiagnosticArray,
            "DiagnosticStatus": DiagnosticStatus,
            "KeyValue": KeyValue,
        },
    )
    _install_module("rclpy.clock", {"Clock": Clock, "ClockType": ClockType})
    _install_module("sensor_msgs.msg", {"Imu": Imu})
    _install_module("std_msgs.msg", {"String": String})
    _install_module("unitree_api.msg", {"Request": Request, "Response": Response})
    _install_module("unitree_hg.msg", {"IMUState": IMUState, "LowState": LowState})
