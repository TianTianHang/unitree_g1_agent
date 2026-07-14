cmake_minimum_required(VERSION 3.8)
project(g1_agent_msgs)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/VoiceEvent.msg"
  "msg/LocoIntent.msg"
  "msg/ActionIntent.msg"
  "msg/RobotStateSummary.msg"
  "msg/SafetyDecision.msg"
  "msg/ValidatedLocoCommand.msg"
  "msg/ValidatedActionCommand.msg"
  "msg/SafetyStatus.msg"
  DEPENDENCIES builtin_interfaces geometry_msgs
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_interfaces test/test_interfaces.py)
endif()

ament_export_dependencies(rosidl_default_runtime)
ament_package()
