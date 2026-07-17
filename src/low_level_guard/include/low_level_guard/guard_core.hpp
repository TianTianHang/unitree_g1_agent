#pragma once

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>

#include <g1_agent_msgs/msg/low_level_command_candidate.hpp>
#include <g1_agent_msgs/msg/low_level_control_lease.hpp>
#include <unitree_hg/msg/low_cmd.hpp>
#include <unitree_hg/msg/low_state.hpp>

namespace low_level_guard
{

struct GuardConfig
{
  std::string robot_profile{"g1_29dof_unitree_v1"};
  std::string control_profile{"textop_tracker_v1"};
  uint8_t mode_pr{0};
  double max_lease_sec{30.0};
  double max_candidate_valid_sec{0.2};
  double lowstate_timeout_sec{0.1};
  double max_abs_q_rad{6.5};
  double max_abs_dq_rad_s{40.0};
  double max_abs_tau_nm{160.0};
  double max_kp{500.0};
  double max_kd{20.0};
  double max_position_error_rad{1.0};
};

class GuardCore
{
public:
  using Clock = std::chrono::steady_clock;
  using TimePoint = Clock::time_point;

  explicit GuardCore(GuardConfig config);

  bool update_lease(
    const g1_agent_msgs::msg::LowLevelControlLease & lease,
    TimePoint now,
    std::string & reason);
  void update_lowstate(const unitree_hg::msg::LowState & lowstate, TimePoint now);
  bool accept_candidate(
    const g1_agent_msgs::msg::LowLevelCommandCandidate & candidate,
    TimePoint now,
    std::string & reason);
  std::optional<unitree_hg::msg::LowCmd> command(TimePoint now, std::string & reason) const;

  bool lease_active(TimePoint now) const;
  bool candidate_fresh(TimePoint now) const;
  bool lowstate_fresh(TimePoint now) const;
  const std::string & last_rejection_reason() const;

private:
  static double duration_sec(int32_t sec, uint32_t nanosec);
  bool validate_candidate_values(
    const g1_agent_msgs::msg::LowLevelCommandCandidate & candidate,
    std::string & reason) const;
  bool reject(const std::string & reason, std::string & output_reason);

  GuardConfig config_;
  std::optional<g1_agent_msgs::msg::LowLevelControlLease> lease_;
  std::optional<g1_agent_msgs::msg::LowLevelCommandCandidate> candidate_;
  std::optional<unitree_hg::msg::LowState> lowstate_;
  TimePoint lease_deadline_{};
  TimePoint candidate_deadline_{};
  TimePoint lowstate_received_at_{};
  uint64_t last_sequence_id_{0};
  bool has_sequence_{false};
  std::string last_rejection_reason_;
};

}  // namespace low_level_guard
