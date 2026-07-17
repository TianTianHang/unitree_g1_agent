#include "low_level_guard/guard_core.hpp"

#include <algorithm>
#include <cmath>
#include <utility>

#include "low_level_guard/crc.hpp"

namespace low_level_guard
{

GuardCore::GuardCore(GuardConfig config)
: config_(std::move(config))
{
}

double GuardCore::duration_sec(int32_t sec, uint32_t nanosec)
{
  return static_cast<double>(sec) + static_cast<double>(nanosec) / 1'000'000'000.0;
}

bool GuardCore::reject(const std::string & reason, std::string & output_reason)
{
  last_rejection_reason_ = reason;
  output_reason = reason;
  return false;
}

bool GuardCore::update_lease(
  const g1_agent_msgs::msg::LowLevelControlLease & lease,
  TimePoint now,
  std::string & reason)
{
  if (!lease.active) {
    if (lease_ && lease.lease_id == lease_->lease_id) {
      lease_.reset();
      candidate_.reset();
      has_sequence_ = false;
    }
    reason.clear();
    return true;
  }
  if (lease.lease_id.empty() || lease.request_id.empty() || lease.owner.empty()) {
    return reject("lease identity fields must be non-empty", reason);
  }
  if (lease.robot_profile != config_.robot_profile) {
    return reject("lease robot_profile mismatch", reason);
  }
  if (lease.control_profile != config_.control_profile) {
    return reject("lease control_profile mismatch", reason);
  }
  const double ttl = duration_sec(lease.ttl.sec, lease.ttl.nanosec);
  if (!std::isfinite(ttl) || ttl <= 0.0 || ttl > config_.max_lease_sec) {
    return reject("lease ttl out of bounds", reason);
  }

  const bool new_lease = !lease_ || lease.lease_id != lease_->lease_id;
  lease_ = lease;
  lease_deadline_ = now + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(ttl));
  if (new_lease) {
    candidate_.reset();
    has_sequence_ = false;
  }
  reason.clear();
  return true;
}

void GuardCore::update_lowstate(const unitree_hg::msg::LowState & lowstate, TimePoint now)
{
  lowstate_ = lowstate;
  lowstate_received_at_ = now;
}

bool GuardCore::validate_candidate_values(
  const g1_agent_msgs::msg::LowLevelCommandCandidate & candidate,
  std::string & reason) const
{
  for (std::size_t index = 0; index < candidate.motors.size(); ++index) {
    const auto & motor = candidate.motors[index];
    if (!std::isfinite(motor.q) || !std::isfinite(motor.dq) || !std::isfinite(motor.tau) ||
      !std::isfinite(motor.kp) || !std::isfinite(motor.kd))
    {
      reason = "candidate contains non-finite motor value";
      return false;
    }
    if (std::abs(motor.q) > config_.max_abs_q_rad ||
      std::abs(motor.dq) > config_.max_abs_dq_rad_s ||
      std::abs(motor.tau) > config_.max_abs_tau_nm || motor.kp < 0.0F ||
      motor.kp > config_.max_kp || motor.kd < 0.0F || motor.kd > config_.max_kd)
    {
      reason = "candidate motor value out of configured bounds";
      return false;
    }
    if (lowstate_ &&
      std::abs(static_cast<double>(motor.q) - lowstate_->motor_state[index].q) >
      config_.max_position_error_rad)
    {
      reason = "candidate target position too far from current state";
      return false;
    }
  }
  return true;
}

bool GuardCore::accept_candidate(
  const g1_agent_msgs::msg::LowLevelCommandCandidate & candidate,
  TimePoint now,
  std::string & reason)
{
  if (!lease_active(now)) {
    return reject("no active low-level lease", reason);
  }
  if (!lowstate_fresh(now)) {
    return reject("lowstate is stale", reason);
  }
  if (candidate.backend_id.empty() || candidate.model_id.empty()) {
    return reject("candidate backend_id and model_id must be non-empty", reason);
  }
  if (candidate.lease_id != lease_->lease_id || candidate.request_id != lease_->request_id) {
    return reject("candidate lease identity mismatch", reason);
  }
  if (candidate.robot_profile != config_.robot_profile ||
    candidate.control_profile != config_.control_profile)
  {
    return reject("candidate control profile mismatch", reason);
  }
  if (has_sequence_ && candidate.sequence_id <= last_sequence_id_) {
    return reject("candidate sequence_id is not increasing", reason);
  }
  const double valid_for = duration_sec(candidate.valid_for.sec, candidate.valid_for.nanosec);
  if (!std::isfinite(valid_for) || valid_for <= 0.0 || valid_for > config_.max_candidate_valid_sec) {
    return reject("candidate valid_for out of bounds", reason);
  }
  if (!validate_candidate_values(candidate, reason)) {
    last_rejection_reason_ = reason;
    return false;
  }

  candidate_ = candidate;
  candidate_deadline_ =
    now + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(valid_for));
  last_sequence_id_ = candidate.sequence_id;
  has_sequence_ = true;
  reason.clear();
  return true;
}

bool GuardCore::lease_active(TimePoint now) const
{
  return lease_.has_value() && lease_->active && now < lease_deadline_;
}

bool GuardCore::candidate_fresh(TimePoint now) const
{
  return candidate_.has_value() && now < candidate_deadline_;
}

bool GuardCore::lowstate_fresh(TimePoint now) const
{
  if (!lowstate_) {
    return false;
  }
  const double age = std::chrono::duration<double>(now - lowstate_received_at_).count();
  return age >= 0.0 && age <= config_.lowstate_timeout_sec;
}

std::optional<unitree_hg::msg::LowCmd> GuardCore::command(TimePoint now, std::string & reason) const
{
  if (!lease_active(now)) {
    reason = "no active low-level lease";
    return std::nullopt;
  }
  if (!lowstate_fresh(now)) {
    reason = "lowstate is stale";
    return std::nullopt;
  }
  if (!candidate_fresh(now)) {
    reason = "candidate is stale";
    return std::nullopt;
  }

  unitree_hg::msg::LowCmd output{};
  output.mode_pr = config_.mode_pr;
  output.mode_machine = lowstate_->mode_machine;
  for (auto & motor : output.motor_cmd) {
    motor.mode = 0;
    motor.q = 0.0F;
    motor.dq = 0.0F;
    motor.tau = 0.0F;
    motor.kp = 0.0F;
    motor.kd = 0.0F;
    motor.reserve = 0U;
  }
  for (std::size_t index = 0; index < candidate_->motors.size(); ++index) {
    const auto & source = candidate_->motors[index];
    auto & target = output.motor_cmd[index];
    target.mode = 1;
    target.q = source.q;
    target.dq = source.dq;
    target.tau = source.tau;
    target.kp = source.kp;
    target.kd = source.kd;
  }
  std::fill(output.reserve.begin(), output.reserve.end(), 0U);
  update_crc(output);
  reason.clear();
  return output;
}

const std::string & GuardCore::last_rejection_reason() const
{
  return last_rejection_reason_;
}

}  // namespace low_level_guard
