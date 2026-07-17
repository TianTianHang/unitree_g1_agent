#include <chrono>
#include <cmath>
#include <limits>
#include <string>

#include <gtest/gtest.h>

#include "low_level_guard/crc.hpp"
#include "low_level_guard/guard_core.hpp"

namespace
{

using low_level_guard::GuardCore;

g1_agent_msgs::msg::LowLevelControlLease make_lease()
{
  g1_agent_msgs::msg::LowLevelControlLease lease;
  lease.lease_id = "lease-1";
  lease.request_id = "request-1";
  lease.owner = "motion_manager";
  lease.robot_profile = "g1_29dof_unitree_v1";
  lease.control_profile = "textop_tracker_v1";
  lease.ttl.sec = 1;
  lease.active = true;
  return lease;
}

unitree_hg::msg::LowState make_lowstate()
{
  unitree_hg::msg::LowState state;
  state.mode_machine = 5;
  for (auto & motor : state.motor_state) {
    motor.q = 0.0F;
    motor.dq = 0.0F;
  }
  return state;
}

g1_agent_msgs::msg::LowLevelCommandCandidate make_candidate(uint64_t sequence_id = 1)
{
  g1_agent_msgs::msg::LowLevelCommandCandidate candidate;
  candidate.backend_id = "textop";
  candidate.model_id = "policy.onnx";
  candidate.request_id = "request-1";
  candidate.lease_id = "lease-1";
  candidate.sequence_id = sequence_id;
  candidate.valid_for.nanosec = 60'000'000U;
  candidate.robot_profile = "g1_29dof_unitree_v1";
  candidate.control_profile = "textop_tracker_v1";
  for (std::size_t index = 0; index < candidate.motors.size(); ++index) {
    candidate.motors[index].q = 0.01F * static_cast<float>(index);
    candidate.motors[index].dq = 0.0F;
    candidate.motors[index].tau = 0.0F;
    candidate.motors[index].kp = 40.0F;
    candidate.motors[index].kd = 2.0F;
  }
  return candidate;
}

GuardCore ready_core(GuardCore::TimePoint now)
{
  GuardCore core(low_level_guard::GuardConfig{});
  std::string reason;
  EXPECT_TRUE(core.update_lease(make_lease(), now, reason)) << reason;
  core.update_lowstate(make_lowstate(), now);
  return core;
}

TEST(GuardCore, MapsValidatedCandidateToUnitreeLowCmd)
{
  const auto now = GuardCore::Clock::now();
  auto core = ready_core(now);
  std::string reason;
  EXPECT_TRUE(core.accept_candidate(make_candidate(), now, reason)) << reason;

  auto command = core.command(now + std::chrono::milliseconds(10), reason);
  ASSERT_TRUE(command.has_value()) << reason;
  EXPECT_EQ(command->mode_pr, 0);
  EXPECT_EQ(command->mode_machine, 5);
  EXPECT_EQ(command->motor_cmd[0].mode, 1);
  EXPECT_FLOAT_EQ(command->motor_cmd[28].q, 0.28F);
  EXPECT_FLOAT_EQ(command->motor_cmd[28].kp, 40.0F);
  EXPECT_EQ(command->motor_cmd[29].mode, 0);
  EXPECT_EQ(command->motor_cmd[34].mode, 0);
  EXPECT_NE(command->crc, 0U);

  auto copy = *command;
  EXPECT_EQ(low_level_guard::update_crc(copy), command->crc);
}

TEST(GuardCore, RejectsReplayedAndNonFiniteCandidates)
{
  const auto now = GuardCore::Clock::now();
  auto core = ready_core(now);
  std::string reason;
  EXPECT_TRUE(core.accept_candidate(make_candidate(7), now, reason));
  EXPECT_FALSE(core.accept_candidate(make_candidate(7), now, reason));
  EXPECT_EQ(reason, "candidate sequence_id is not increasing");

  auto invalid = make_candidate(8);
  invalid.motors[3].q = std::numeric_limits<float>::quiet_NaN();
  EXPECT_FALSE(core.accept_candidate(invalid, now, reason));
  EXPECT_EQ(reason, "candidate contains non-finite motor value");
}

TEST(GuardCore, StopsProducingCommandsWhenCandidateOrLeaseExpires)
{
  const auto now = GuardCore::Clock::now();
  auto core = ready_core(now);
  std::string reason;
  EXPECT_TRUE(core.accept_candidate(make_candidate(), now, reason));

  EXPECT_FALSE(core.command(now + std::chrono::milliseconds(61), reason).has_value());
  EXPECT_EQ(reason, "candidate is stale");
  EXPECT_FALSE(core.command(now + std::chrono::milliseconds(1001), reason).has_value());
  EXPECT_EQ(reason, "no active low-level lease");
}

TEST(GuardCore, RejectsMismatchedLeaseAndUnsafePositionJump)
{
  const auto now = GuardCore::Clock::now();
  auto core = ready_core(now);
  std::string reason;
  auto mismatch = make_candidate();
  mismatch.lease_id = "other";
  EXPECT_FALSE(core.accept_candidate(mismatch, now, reason));
  EXPECT_EQ(reason, "candidate lease identity mismatch");

  auto unsafe = make_candidate();
  unsafe.motors[0].q = 1.1F;
  EXPECT_FALSE(core.accept_candidate(unsafe, now, reason));
  EXPECT_EQ(reason, "candidate target position too far from current state");
}

}  // namespace
