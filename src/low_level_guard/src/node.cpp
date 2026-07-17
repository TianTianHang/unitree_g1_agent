#include <chrono>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

#include <diagnostic_msgs/msg/diagnostic_array.hpp>
#include <diagnostic_msgs/msg/diagnostic_status.hpp>
#include <diagnostic_msgs/msg/key_value.hpp>
#include <g1_agent_msgs/msg/low_level_command_candidate.hpp>
#include <g1_agent_msgs/msg/low_level_control_lease.hpp>
#include <rclcpp/rclcpp.hpp>
#include <unitree_hg/msg/low_cmd.hpp>
#include <unitree_hg/msg/low_state.hpp>

#include "low_level_guard/guard_core.hpp"

namespace low_level_guard
{

class LowLevelGuardNode : public rclcpp::Node
{
public:
  LowLevelGuardNode()
  : Node("low_level_guard_node"), core_(load_config())
  {
    const auto candidate_topic = declare_parameter<std::string>(
      "topics.candidate", "/g1/low_level/candidate");
    const auto lease_topic = declare_parameter<std::string>(
      "topics.lease", "/g1/low_level/lease");
    const auto lowstate_topic = declare_parameter<std::string>(
      "topics.lowstate", "/lowstate");
    const auto lowcmd_topic = declare_parameter<std::string>(
      "topics.lowcmd", "/lowcmd");
    const auto diagnostics_topic = declare_parameter<std::string>(
      "topics.diagnostics", "/g1/low_level_guard/diagnostics");
    const double publish_hz = declare_parameter<double>("publish_hz", 500.0);
    if (!std::isfinite(publish_hz) || publish_hz <= 0.0) {
      throw std::invalid_argument("publish_hz must be positive and finite");
    }

    lowcmd_pub_ = create_publisher<unitree_hg::msg::LowCmd>(lowcmd_topic, 10);
    diagnostics_pub_ = create_publisher<diagnostic_msgs::msg::DiagnosticArray>(diagnostics_topic, 10);
    candidate_sub_ = create_subscription<g1_agent_msgs::msg::LowLevelCommandCandidate>(
      candidate_topic, 10,
      [this](const g1_agent_msgs::msg::LowLevelCommandCandidate::SharedPtr message) {
        std::string reason;
        if (!core_.accept_candidate(*message, GuardCore::Clock::now(), reason)) {
          RCLCPP_WARN(get_logger(), "rejected low-level candidate: %s", reason.c_str());
        }
      });
    lease_sub_ = create_subscription<g1_agent_msgs::msg::LowLevelControlLease>(
      lease_topic, 10,
      [this](const g1_agent_msgs::msg::LowLevelControlLease::SharedPtr message) {
        std::string reason;
        if (!core_.update_lease(*message, GuardCore::Clock::now(), reason)) {
          RCLCPP_WARN(get_logger(), "rejected low-level lease: %s", reason.c_str());
        }
      });
    lowstate_sub_ = create_subscription<unitree_hg::msg::LowState>(
      lowstate_topic, rclcpp::SensorDataQoS(),
      [this](const unitree_hg::msg::LowState::SharedPtr message) {
        core_.update_lowstate(*message, GuardCore::Clock::now());
      });

    const auto period = std::chrono::duration<double>(1.0 / publish_hz);
    publish_timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(period),
      [this]() {publish_command();});
    diagnostics_timer_ = create_wall_timer(
      std::chrono::seconds(1), [this]() {publish_diagnostics();});
  }

private:
  GuardConfig load_config()
  {
    GuardConfig config;
    config.robot_profile = declare_parameter<std::string>(
      "robot_profile", config.robot_profile);
    config.control_profile = declare_parameter<std::string>(
      "control_profile", config.control_profile);
    const auto mode_pr = declare_parameter<int64_t>("mode_pr", config.mode_pr);
    if (mode_pr < 0 || mode_pr > 1) {
      throw std::invalid_argument("mode_pr must be 0 (PR) or 1 (AB)");
    }
    config.mode_pr = static_cast<uint8_t>(mode_pr);
    config.max_lease_sec = declare_parameter<double>("limits.max_lease_sec", config.max_lease_sec);
    config.max_candidate_valid_sec = declare_parameter<double>(
      "limits.max_candidate_valid_sec", config.max_candidate_valid_sec);
    config.lowstate_timeout_sec = declare_parameter<double>(
      "limits.lowstate_timeout_sec", config.lowstate_timeout_sec);
    config.max_abs_q_rad = declare_parameter<double>("limits.max_abs_q_rad", config.max_abs_q_rad);
    config.max_abs_dq_rad_s = declare_parameter<double>(
      "limits.max_abs_dq_rad_s", config.max_abs_dq_rad_s);
    config.max_abs_tau_nm = declare_parameter<double>(
      "limits.max_abs_tau_nm", config.max_abs_tau_nm);
    config.max_kp = declare_parameter<double>("limits.max_kp", config.max_kp);
    config.max_kd = declare_parameter<double>("limits.max_kd", config.max_kd);
    config.max_position_error_rad = declare_parameter<double>(
      "limits.max_position_error_rad", config.max_position_error_rad);
    return config;
  }

  void publish_command()
  {
    std::string reason;
    auto command = core_.command(GuardCore::Clock::now(), reason);
    if (command) {
      lowcmd_pub_->publish(*command);
      publishing_ = true;
      last_gate_reason_.clear();
    } else {
      publishing_ = false;
      last_gate_reason_ = std::move(reason);
    }
  }

  void publish_diagnostics()
  {
    const auto now = GuardCore::Clock::now();
    diagnostic_msgs::msg::DiagnosticArray array;
    array.header.stamp = get_clock()->now();
    diagnostic_msgs::msg::DiagnosticStatus status;
    status.name = "low_level_guard";
    status.hardware_id = "g1_lowcmd";
    status.level = publishing_ ? diagnostic_msgs::msg::DiagnosticStatus::OK :
      diagnostic_msgs::msg::DiagnosticStatus::WARN;
    status.message = publishing_ ? "publishing validated lowcmd" :
      (last_gate_reason_.empty() ? "guard idle" : last_gate_reason_);
    const auto add_value = [&status](std::string key, std::string value) {
        diagnostic_msgs::msg::KeyValue item;
        item.key = std::move(key);
        item.value = std::move(value);
        status.values.push_back(std::move(item));
      };
    add_value("lease_active", core_.lease_active(now) ? "true" : "false");
    add_value("candidate_fresh", core_.candidate_fresh(now) ? "true" : "false");
    add_value("lowstate_fresh", core_.lowstate_fresh(now) ? "true" : "false");
    add_value("last_rejection", core_.last_rejection_reason());
    array.status.push_back(std::move(status));
    diagnostics_pub_->publish(array);
  }

  GuardCore core_;
  bool publishing_{false};
  std::string last_gate_reason_;
  rclcpp::Publisher<unitree_hg::msg::LowCmd>::SharedPtr lowcmd_pub_;
  rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr diagnostics_pub_;
  rclcpp::Subscription<g1_agent_msgs::msg::LowLevelCommandCandidate>::SharedPtr candidate_sub_;
  rclcpp::Subscription<g1_agent_msgs::msg::LowLevelControlLease>::SharedPtr lease_sub_;
  rclcpp::Subscription<unitree_hg::msg::LowState>::SharedPtr lowstate_sub_;
  rclcpp::TimerBase::SharedPtr publish_timer_;
  rclcpp::TimerBase::SharedPtr diagnostics_timer_;
};

}  // namespace low_level_guard

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<low_level_guard::LowLevelGuardNode>());
  rclcpp::shutdown();
  return 0;
}
