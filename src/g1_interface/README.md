# g1_interface

ROS2 Python interface node for Unitree G1 P0 state bridging and high-level sport API commands.

## Development

```bash
make bootstrap
make build
make test
make test-integration
```

The root Makefile creates the Python 3.10 uv environment and sources either
`result/setup.bash` or the Unitree ROS workspace selected by
`UNITREE_ROS2_WS`.

## Launch

```bash
ros2 launch g1_interface g1_interface.launch.py \
  config_path:=src/g1_interface/config/g1_interface.yaml
```

## Read-Only Verification

```bash
ros2 topic echo /g1/state/health
ros2 topic echo /g1/state/low
ros2 topic echo /g1/state/imu
```

## Safe Command Smoke Test

Run this only after `/g1/state/health` reports fresh lowstate data and the robot is in a safe test posture.

```bash
ros2 topic pub --once /voice/cmd/action g1_agent_msgs/msg/ActionIntent \
  "{source: cli, session_id: smoke, command_id: cli-stop-1, text: '停止', action: stop, priority: emergency}"
ros2 topic echo /api/sport/request
```

This publishes an intent through `safety_control`; do not bypass the safety
node by constructing a validated command manually.

## Motion Watchdog and Health Semantics

`g1_interface` keeps the Sport API firmware `duration` field and also runs an
independent local watchdog. Safety deadlines and freshness checks use a
monotonic clock; the watchdog timer uses ROS 2 `STEADY_TIME`.

The node actively sends a zero-velocity Sport API request when:

- the commanded motion duration reaches its local deadline;
- `/g1/state/safety` has not received a `safety_control` heartbeat for 1200 ms;
- lowstate telemetry is stale while motion is active;
- a motion request is rejected or is not acknowledged before the API timeout;
- the node shuts down.

Explicit safe-stop, watchdog-stop, and shutdown-stop requests bypass lowstate,
mode, and heartbeat freshness gates. New loco commands require fresh lowstate,
a fresh safety heartbeat, a successful mode query within 1500 ms, internal
`sport_api_loco` ownership, and no unacknowledged velocity request.

`/g1/state/health` includes Sport response age, successful mode-query age,
consecutive API timeouts, the latest command acknowledgement, mode and safety
freshness, and an inferred DDS connection state. Diagnostic levels are `OK`
for `ok`, `WARN` for `degraded`, and `ERROR` for `unhealthy`.
