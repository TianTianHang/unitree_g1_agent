SHELL := /bin/bash
UV_ENV := .venv-ros
UV_RUN := UV_PROJECT_ENVIRONMENT=$(UV_ENV) uv run --frozen
COMMON_REPO_ROOT := $(shell cd "$$(git rev-parse --git-common-dir)/.." && pwd -P)
UNITREE_ROS2_WS ?= $(COMMON_REPO_ROOT)/.unitree/unitree_ros2/cyclonedds_ws
UNITREE_SETUP := $(UNITREE_ROS2_WS)/install/setup.bash
PYTEST_PATHS := \
	src/g1_agent_msgs/test \
	src/asr_node/tests \
	src/g1_interface/tests \
	src/g1_sim/tests \
	src/safety_control/tests \
	src/voice_bridge/tests \
	src/voice_bridge_debug/tests
ROS_SETUP := source /opt/ros/humble/setup.bash; \
	if [[ -f result/setup.bash ]]; then \
		source result/setup.bash; \
	elif ros2 pkg prefix unitree_api >/dev/null 2>&1; then \
		:; \
	elif [[ -f "$(UNITREE_SETUP)" ]]; then \
		source "$(UNITREE_SETUP)"; \
	else \
		echo "Unitree ROS 2 overlay not found; build UNITREE_ROS2_WS or provide result/setup.bash" >&2; \
		exit 1; \
	fi

export PYTHONNOUSERSITE := 1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD := 1
export UV_PROJECT_ENVIRONMENT := $(UV_ENV)

.PHONY: bootstrap bootstrap-asr build test test-integration lint frontend

bootstrap:
	@test "$$($(abspath /usr/bin/python3) -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))')" = "3.10"
	@test "$$(uv --version | awk '{print $$1, $$2}')" = "uv 0.11.26"
	@if [[ ! -d $(UV_ENV) ]]; then uv venv --python /usr/bin/python3 --system-site-packages $(UV_ENV); fi
	@test "$$($(UV_ENV)/bin/python -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))')" = "3.10"
	@grep -Fq 'include-system-site-packages = true' $(UV_ENV)/pyvenv.cfg
	@uv sync --frozen

bootstrap-asr: bootstrap
	@uv sync --frozen --group asr

build: bootstrap
	@$(ROS_SETUP); colcon build --symlink-install --event-handlers console_direct+

test: build
	@$(ROS_SETUP); source install/setup.bash; set -e; \
		for test_path in $(PYTEST_PATHS); do \
			$(UV_RUN) python -m pytest -q "$$test_path"; \
		done
	@$(ROS_SETUP); source install/setup.bash; \
		colcon test --packages-select low_level_guard --event-handlers console_direct+; \
		colcon test-result --test-result-base build/low_level_guard/test_results --verbose

test-integration: build
	@$(ROS_SETUP); source install/setup.bash; colcon test --packages-select g1_system_tests --event-handlers console_direct+
	@$(ROS_SETUP); source install/setup.bash; colcon test-result --test-result-base build/g1_system_tests/test_results --verbose

lint: build
	@$(ROS_SETUP); source install/setup.bash; $(UV_RUN) ruff check src
	@$(ROS_SETUP); source install/setup.bash; $(UV_RUN) pyright

frontend:
	@npm --prefix src/voice_bridge_debug/frontend ci
	@npm --prefix src/voice_bridge_debug/frontend run build
	@git diff --exit-code -- src/voice_bridge_debug/voice_bridge_debug/frontend_dist
