#include "low_level_guard/crc.hpp"

#include <array>
#include <cstddef>
#include <cstring>

namespace low_level_guard
{
namespace
{

struct MotorCommandWire
{
  uint8_t mode{};
  std::array<uint8_t, 3> padding{};
  float q{};
  float dq{};
  float tau{};
  float kp{};
  float kd{};
  uint32_t reserve{};
};

struct LowCommandWire
{
  uint8_t mode_pr{};
  uint8_t mode_machine{};
  std::array<uint8_t, 2> padding{};
  std::array<MotorCommandWire, 35> motor_cmd{};
  std::array<uint32_t, 4> reserve{};
  uint32_t crc{};
};

static_assert(sizeof(MotorCommandWire) == 28);
static_assert(offsetof(LowCommandWire, crc) == 1000);
static_assert(sizeof(LowCommandWire) == 1004);

}  // namespace

uint32_t crc32_core(const uint32_t * words, uint32_t word_count)
{
  uint32_t crc = 0xFFFFFFFFU;
  constexpr uint32_t polynomial = 0x04C11DB7U;
  for (uint32_t index = 0; index < word_count; ++index) {
    uint32_t bit = 1U << 31U;
    const uint32_t data = words[index];
    for (uint32_t count = 0; count < 32U; ++count) {
      if ((crc & 0x80000000U) != 0U) {
        crc = (crc << 1U) ^ polynomial;
      } else {
        crc <<= 1U;
      }
      if ((data & bit) != 0U) {
        crc ^= polynomial;
      }
      bit >>= 1U;
    }
  }
  return crc;
}

uint32_t update_crc(unitree_hg::msg::LowCmd & message)
{
  LowCommandWire wire{};
  wire.mode_pr = message.mode_pr;
  wire.mode_machine = message.mode_machine;
  for (std::size_t index = 0; index < wire.motor_cmd.size(); ++index) {
    wire.motor_cmd[index].mode = message.motor_cmd[index].mode;
    wire.motor_cmd[index].q = message.motor_cmd[index].q;
    wire.motor_cmd[index].dq = message.motor_cmd[index].dq;
    wire.motor_cmd[index].tau = message.motor_cmd[index].tau;
    wire.motor_cmd[index].kp = message.motor_cmd[index].kp;
    wire.motor_cmd[index].kd = message.motor_cmd[index].kd;
    wire.motor_cmd[index].reserve = message.motor_cmd[index].reserve;
  }
  wire.reserve = message.reserve;

  std::array<uint32_t, 250> words{};
  std::memcpy(words.data(), &wire, words.size() * sizeof(uint32_t));
  message.crc = crc32_core(words.data(), static_cast<uint32_t>(words.size()));
  return message.crc;
}

}  // namespace low_level_guard
