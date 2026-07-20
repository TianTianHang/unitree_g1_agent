cmake_minimum_required(VERSION 3.8)
project(g1_system_tests)

find_package(ament_cmake REQUIRED)

install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
install(PROGRAMS
  test/support/textop_generator_test_node
  test/support/textop_tracker_test_node
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(launch_testing_ament_cmake REQUIRED)
  add_launch_test(test/test_typed_control_chain.py TIMEOUT 60)
  add_launch_test(test/test_textop_control_chain.py TIMEOUT 90)
endif()

ament_package()
