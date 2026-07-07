import os
from pathlib import Path

import pytest

from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.pi_agent import PiRpcTransport
from voice_bridge.pi_config import build_pi_command, resolve_workspace, scrubbed_env

PI_AGENT_INTEGRATION = os.environ.get("PI_AGENT_INTEGRATION", "")


@pytest.mark.skipif(not PI_AGENT_INTEGRATION, reason="Pi not available")
def test_pi_rpc_get_state_smoke():
    repo_root = Path.cwd()
    config = VoiceBridgeConfig.default()
    pi_config = dict(config.agent["pi"])
    workspace = resolve_workspace(pi_config, repo_root)
    transport = PiRpcTransport()
    try:
        transport.start(build_pi_command(pi_config, workspace), workspace, scrubbed_env(pi_config))
        response = transport.send({"type": "get_state"}, timeout=20.0)
        assert response["type"] == "response"
        assert response["success"] is True
        assert "sessionId" in response.get("data", {})
    finally:
        transport.close()
