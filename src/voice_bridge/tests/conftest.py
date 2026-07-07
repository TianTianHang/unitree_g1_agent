import sys
import types


def _install_diagnostic_msgs_stub() -> None:
    try:
        import diagnostic_msgs.msg  # noqa: F401
    except ModuleNotFoundError:
        diagnostic_msgs = types.ModuleType("diagnostic_msgs")
        msg = types.ModuleType("diagnostic_msgs.msg")

        class DiagnosticStatus:
            def __init__(self):
                self.name = ""
                self.level = 0
                self.message = ""

        class DiagnosticArray:
            def __init__(self):
                self.status = []

        msg.DiagnosticArray = DiagnosticArray
        msg.DiagnosticStatus = DiagnosticStatus
        diagnostic_msgs.msg = msg
        sys.modules["diagnostic_msgs"] = diagnostic_msgs
        sys.modules["diagnostic_msgs.msg"] = msg


_install_diagnostic_msgs_stub()
