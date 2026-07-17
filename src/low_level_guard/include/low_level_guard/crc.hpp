#pragma once

#include <cstdint>

#include <unitree_hg/msg/low_cmd.hpp>

namespace low_level_guard
{

uint32_t crc32_core(const uint32_t * words, uint32_t word_count);
uint32_t update_crc(unitree_hg::msg::LowCmd & message);

}  // namespace low_level_guard
