from types import SimpleNamespace

from g1_interface.converters import imu_to_payload, lowstate_to_summary


def _motor(q, dq, tau, temperature):
    return SimpleNamespace(q=q, dq=dq, tau_est=tau, temperature=temperature)


def test_lowstate_summary_extracts_imu_and_motor_ranges():
    msg = SimpleNamespace(
        rpy=[0.1, -0.2, 0.3],
        quaternion=[1.0, 0.0, 0.0, 0.0],
        gyroscope=[0.01, 0.02, 0.03],
        accelerometer=[0.0, 0.0, 9.81],
        motor_state=[
            _motor(0.1, 0.2, 0.3, 40),
            _motor(-0.1, -0.2, -0.3, 42),
        ],
    )

    summary = lowstate_to_summary(msg, source="lowstate", max_motors=35)

    assert summary.source == "lowstate"
    assert summary.motor_count == 2
    assert summary.max_temperature_c == 42
    assert summary.rpy == [0.1, -0.2, 0.3]
    assert summary.motors[0]["q"] == 0.1
    assert '"source": "lowstate"' in summary.to_json()


def test_lowstate_summary_handles_missing_optional_arrays():
    msg = SimpleNamespace(motor_state=[])

    summary = lowstate_to_summary(msg, source="lf/lowstate")

    assert summary.source == "lf/lowstate"
    assert summary.motor_count == 0
    assert summary.rpy == [0.0, 0.0, 0.0]
    assert summary.quaternion == [1.0, 0.0, 0.0, 0.0]


def test_imu_payload_uses_ros_quaternion_order():
    msg = SimpleNamespace(
        quaternion=[1.0, 0.1, 0.2, 0.3],
        gyroscope=[0.4, 0.5, 0.6],
        accelerometer=[0.7, 0.8, 0.9],
    )

    payload = imu_to_payload(msg, frame_id="g1_torso")

    assert payload.frame_id == "g1_torso"
    assert payload.orientation_xyzw == [0.1, 0.2, 0.3, 1.0]
    assert payload.angular_velocity == [0.4, 0.5, 0.6]
    assert payload.linear_acceleration == [0.7, 0.8, 0.9]
