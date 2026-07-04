# g1_interface

ROS2 Python interface node for Unitree G1 P0 state bridging and high-level sport API commands.

## Unit Tests

```bash
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests -q
```

## Build

```bash
source /opt/ros/humble/setup.bash
source <unitree_ros2_install>/setup.bash
colcon build --symlink-install --packages-select g1_interface
source install/setup.bash
```

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
ros2 topic pub /g1/safe_cmd/stop std_msgs/msg/String '{data: "{}"}' --once
ros2 topic echo /api/sport/request
```
