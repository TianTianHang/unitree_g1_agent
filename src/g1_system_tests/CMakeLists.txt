cmake_minimum_required(VERSION 3.8)
project(g1_system_tests)

find_package(ament_cmake REQUIRED)

install(DIRECTORY config DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(launch_testing_ament_cmake REQUIRED)
  add_launch_test(test/test_typed_control_chain.py TIMEOUT 60)
endif()

ament_package()
