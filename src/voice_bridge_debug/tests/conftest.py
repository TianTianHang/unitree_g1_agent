import sys
import types


def _install_diagnostic_msgs_stub() -> None:
    try:
        import diagnostic_msgs.msg as msg
    except ModuleNotFoundError:
        diagnostic_msgs = types.ModuleType("diagnostic_msgs")
        msg = types.ModuleType("diagnostic_msgs.msg")
        diagnostic_msgs.msg = msg
        sys.modules["diagnostic_msgs"] = diagnostic_msgs
        sys.modules["diagnostic_msgs.msg"] = msg

    class KeyValue:
        def __init__(self):
            self.key = ""
            self.value = ""

    class DiagnosticStatus:
        def __init__(self):
            self.name = ""
            self.level = 0
            self.message = ""
            self.values = []

    class DiagnosticArray:
        def __init__(self):
            self.status = []

    msg.KeyValue = KeyValue
    msg.DiagnosticArray = DiagnosticArray
    msg.DiagnosticStatus = DiagnosticStatus


_install_diagnostic_msgs_stub()
