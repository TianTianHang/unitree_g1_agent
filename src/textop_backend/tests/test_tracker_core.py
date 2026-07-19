import numpy as np

from textop_backend.tracker import RobotState, body_vector_to_world, build_observation, decode_action


def test_body_vector_to_world_uses_pelvis_orientation():
    half_sqrt = np.sqrt(0.5).astype(np.float32)
    orientation = np.array([half_sqrt, 0.0, 0.0, half_sqrt], dtype=np.float32)

    result = body_vector_to_world(orientation, np.array([1.0, 0.0, 0.0], dtype=np.float32))

    np.testing.assert_allclose(result, [0.0, 1.0, 0.0], atol=1e-6)


def test_observation_has_exact_431_abi_and_expected_slices():
    positions = np.arange(145, dtype=np.float32).reshape(5, 29)
    velocities = (1000 + np.arange(145, dtype=np.float32)).reshape(5, 29)
    anchors = np.tile([1.0, 2.0, 3.0], (5, 1)).astype(np.float32)
    quaternions = np.tile([1.0, 0.0, 0.0, 0.0], (5, 1)).astype(np.float32)
    state = RobotState(
        anchor_position_w=np.zeros(3, dtype=np.float32),
        anchor_orientation_wxyz=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        linear_velocity_w=np.array([4.0, 5.0, 6.0], dtype=np.float32),
        angular_velocity_b=np.array([7.0, 8.0, 9.0], dtype=np.float32),
        joint_position_unitree=np.arange(29, dtype=np.float32),
        joint_velocity_unitree=np.arange(29, dtype=np.float32) + 30,
    )
    last_action = np.arange(29, dtype=np.float32) + 60
    unitree_to_isaaclab = tuple(reversed(range(29)))

    obs = build_observation(
        positions,
        velocities,
        anchors,
        quaternions,
        state,
        last_action,
        default_q_unitree=np.zeros(29, dtype=np.float32),
        unitree_to_isaaclab=unitree_to_isaaclab,
    )

    assert obs.shape == (431,)
    np.testing.assert_array_equal(obs[:145], positions.reshape(-1))
    np.testing.assert_array_equal(obs[145:290], velocities.reshape(-1))
    np.testing.assert_array_equal(obs[290:305], anchors.reshape(-1))
    np.testing.assert_array_equal(obs[305:335], np.tile([1, 0, 0, 1, 0, 0], 5))
    np.testing.assert_array_equal(obs[338:341], [4, 5, 6])
    np.testing.assert_array_equal(obs[344:373], np.arange(29, dtype=np.float32)[::-1])
    np.testing.assert_array_equal(obs[402:431], last_action)


def test_decode_action_reorders_to_unitree_and_sets_impedance_fields():
    raw = np.arange(29, dtype=np.float32)
    isaaclab_to_unitree = tuple(reversed(range(29)))
    command = decode_action(
        raw,
        isaaclab_to_unitree=isaaclab_to_unitree,
        default_q_unitree=np.ones(29, dtype=np.float32),
        action_scale_unitree=np.full(29, 0.5, dtype=np.float32),
        kp_unitree=np.full(29, 40.0, dtype=np.float32),
        kd_unitree=np.full(29, 1.0, dtype=np.float32),
    )

    np.testing.assert_array_equal(command.q, 1.0 + raw[::-1] * 0.5)
    np.testing.assert_array_equal(command.dq, np.zeros(29))
    np.testing.assert_array_equal(command.tau, np.zeros(29))
    np.testing.assert_array_equal(command.kp, np.full(29, 40.0))
    np.testing.assert_array_equal(command.kd, np.full(29, 1.0))
