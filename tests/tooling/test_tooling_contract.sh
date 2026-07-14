#!/usr/bin/env bash
set -euo pipefail

test -f pyproject.toml
test -f uv.lock
test -f Makefile
grep -Fq 'requires-python = "==3.10.*"' pyproject.toml
grep -Fq 'package = false' pyproject.toml
grep -Fq '.venv-ros/' .gitignore
grep -Fq 'UNITREE_ROS2_WS ?=' Makefile
grep -Fq 'ros2 pkg prefix unitree_api' Makefile
grep -Fq 'PYTEST_PATHS :=' Makefile
grep -Fq 'for test_path in $(PYTEST_PATHS)' Makefile
grep -Fq 'colcon test-result --test-result-base build/g1_system_tests/test_results --verbose' Makefile

for target in bootstrap bootstrap-asr build test test-integration lint frontend; do
  make -pn | grep -E "^${target}:" >/dev/null
done

test "$(uv --version | awk '{print $1, $2}')" = "uv 0.11.26"
