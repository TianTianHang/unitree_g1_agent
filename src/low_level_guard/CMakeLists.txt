cmake_minimum_required(VERSION 3.8)
project(low_level_guard)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ament_cmake REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(g1_agent_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(unitree_hg REQUIRED)

add_library(low_level_guard_core
  src/crc.cpp
  src/guard_core.cpp
)
target_include_directories(low_level_guard_core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
ament_target_dependencies(low_level_guard_core
  g1_agent_msgs
  unitree_hg
)

add_executable(low_level_guard_node src/node.cpp)
target_link_libraries(low_level_guard_node low_level_guard_core)
ament_target_dependencies(low_level_guard_node
  diagnostic_msgs
  g1_agent_msgs
  rclcpp
  unitree_hg
)

install(TARGETS low_level_guard_core low_level_guard_node
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})
install(FILES package.xml DESTINATION share/${PROJECT_NAME})
install(FILES resource/${PROJECT_NAME}
  DESTINATION share/ament_index/resource_index/packages
)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_guard_core test/test_guard_core.cpp)
  target_link_libraries(test_guard_core low_level_guard_core)
  ament_target_dependencies(test_guard_core g1_agent_msgs unitree_hg)
endif()

ament_export_include_directories(include)
ament_export_libraries(low_level_guard_core)
ament_export_dependencies(g1_agent_msgs unitree_hg)
ament_package()
