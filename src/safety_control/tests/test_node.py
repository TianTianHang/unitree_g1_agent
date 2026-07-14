def test_allowed_loco_publishes_validated_command_and_decision(ready_node, loco_msg):
    ready_node.bridge.on_loco_intent(loco_msg)

    safe = ready_node.publishers["/g1/safe_cmd/loco"].messages[-1]
    audit = ready_node.publishers["/g1/safety/decisions"].messages[-1]
    assert safe.intent.command_id == loco_msg.command_id
    assert safe.validation.decision == safe.validation.DECISION_ALLOW
    assert audit.command_kind == audit.KIND_LOCO


def test_stop_publishes_validated_action_without_robot_state(bridge_node, stop_msg):
    bridge_node.bridge.on_action_intent(stop_msg)

    safe = bridge_node.publishers["/g1/safe_cmd/stop"].messages[-1]
    assert safe.intent.action == "stop"
    assert safe.validation.decision == safe.validation.DECISION_ALLOW


def test_safety_status_is_typed_heartbeat(ready_node):
    ready_node.bridge.publish_safety_state()

    status = ready_node.publishers["/g1/state/safety"].messages[-1]
    assert status.node_name == "safety_control"
    assert status.enabled is True
