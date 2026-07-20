SHELL := /bin/bash
COMMON_REPO_ROOT := $(shell cd "$$(git rev-parse --git-common-dir)/.." && pwd -P)
ROS_ENV := $(COMMON_REPO_ROOT)/.venv-ros
TEXTOP_ENV := $(COMMON_REPO_ROOT)/.venv-textop
TEXTOP_BUILD_BASE := $(COMMON_REPO_ROOT)/build-textop
TEXTOP_INSTALL_BASE := $(COMMON_REPO_ROOT)/install-textop
UV_RUN := UV_PROJECT_ENVIRONMENT=$(ROS_ENV) uv run --frozen
TEXTOP_UV_RUN := UV_PROJECT_ENVIRONMENT=$(TEXTOP_ENV) uv run --frozen --no-default-groups --group textop
TEXTOP_CUDNN_ENV := $(COMMON_REPO_ROOT)/.unitree/textop-cudnn8-venv
TEXTOP_CUDNN_LIB_DIR := $(TEXTOP_CUDNN_ENV)/lib/python3.10/site-packages/nvidia/cudnn/lib
TEXTOP_CLIP_PATH := $(COMMON_REPO_ROOT)/.unitree/models/textop/ViT-B-32.pt
TEXTOP_CLIP_SHA256 := 40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af
TEXTOP_CLIP_URL := https://openaipublic.azureedge.net/clip/models/$(TEXTOP_CLIP_SHA256)/ViT-B-32.pt
UNITREE_ROS2_WS ?= $(COMMON_REPO_ROOT)/.unitree/unitree_ros2/cyclonedds_ws
UNITREE_SETUP := $(UNITREE_ROS2_WS)/install/setup.bash
PYTEST_PATHS := \
	src/g1_agent_msgs/test \
	src/asr_node/tests \
	src/g1_interface/tests \
	src/g1_sim/tests \
	src/safety_control/tests \
	src/textop_backend/tests \
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
export UV_PROJECT_ENVIRONMENT := $(ROS_ENV)
export TEXTOP_CUDNN_LIB_DIR

.PHONY: bootstrap-env bootstrap bootstrap-asr bootstrap-textop-env bootstrap-textop build build-textop \
	test test-textop test-integration lint lint-textop check-textop-core check-textop frontend

bootstrap-env:
	@test "$$($(abspath /usr/bin/python3) -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))')" = "3.10"
	@uv --version >/dev/null
	@if [[ ! -d $(ROS_ENV) ]]; then uv venv --python /usr/bin/python3 --system-site-packages $(ROS_ENV); fi
	@test "$$($(ROS_ENV)/bin/python -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))')" = "3.10"
	@grep -Fq 'include-system-site-packages = true' $(ROS_ENV)/pyvenv.cfg

bootstrap: bootstrap-env
	@uv sync --frozen

bootstrap-asr: bootstrap-env
	@uv sync --frozen --group asr

bootstrap-textop-env:
	@test "$$($(abspath /usr/bin/python3) -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))')" = "3.10"
	@uv --version >/dev/null
	@if [[ ! -d $(TEXTOP_ENV) ]]; then uv venv --python /usr/bin/python3 --system-site-packages $(TEXTOP_ENV); fi
	@test "$$($(TEXTOP_ENV)/bin/python -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))')" = "3.10"
	@grep -Fq 'include-system-site-packages = true' $(TEXTOP_ENV)/pyvenv.cfg

bootstrap-textop: bootstrap-textop-env
	@if [[ ! -d $(TEXTOP_CUDNN_ENV) ]]; then uv venv --python /usr/bin/python3 $(TEXTOP_CUDNN_ENV); fi
	@UV_PROJECT_ENVIRONMENT=$(TEXTOP_CUDNN_ENV) uv sync --frozen --no-default-groups --group textop_cudnn8
	@$(TEXTOP_UV_RUN) python -c 'import numpy, onnxruntime, torch; assert str(torch.__version__).startswith("2.5.1")'
	@mkdir -p $$(dirname $(TEXTOP_CLIP_PATH))
	@if [[ ! -f $(TEXTOP_CLIP_PATH) ]]; then \
		curl --fail --location $(TEXTOP_CLIP_URL) --output $(TEXTOP_CLIP_PATH).tmp; \
		echo "$(TEXTOP_CLIP_SHA256)  $(TEXTOP_CLIP_PATH).tmp" | sha256sum --check -; \
		mv $(TEXTOP_CLIP_PATH).tmp $(TEXTOP_CLIP_PATH); \
	fi
	@echo "$(TEXTOP_CLIP_SHA256)  $(TEXTOP_CLIP_PATH)" | sha256sum --check -

build: bootstrap
	@$(ROS_SETUP); colcon build --symlink-install --event-handlers console_direct+

build-textop: build bootstrap-textop
	@$(ROS_SETUP); $(TEXTOP_ENV)/bin/python -m colcon build \
		--packages-select g1_agent_msgs textop_backend \
		--build-base $(TEXTOP_BUILD_BASE) --install-base $(TEXTOP_INSTALL_BASE) \
		--symlink-install --event-handlers console_direct+

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

test-textop: build-textop
	@$(ROS_SETUP); source install/setup.bash; source $(TEXTOP_INSTALL_BASE)/setup.bash; \
		$(TEXTOP_UV_RUN) python -m pytest -q src/textop_backend/tests

lint-textop: bootstrap
	@$(UV_RUN) ruff check src/textop_backend --exclude src/textop_backend/textop_backend/textop_model
	@$(UV_RUN) pyright src/textop_backend/textop_backend

check-textop-core: bootstrap
	@PYTHONPATH=src/textop_backend $(UV_RUN) python -m pytest -q src/textop_backend/tests
	@$(UV_RUN) ruff check src/textop_backend --exclude src/textop_backend/textop_backend/textop_model
	@$(UV_RUN) pyright src/textop_backend/textop_backend

check-textop: test-textop lint-textop
	@$(TEXTOP_ENV)/bin/python -c 'import sys; assert sys.prefix == "$(TEXTOP_ENV)"; print("TextOp environment:", sys.prefix)'
	@grep -Fxq '#!$(TEXTOP_ENV)/bin/python' \
		$(TEXTOP_INSTALL_BASE)/textop_backend/lib/textop_backend/textop_generator_node

frontend:
	@npm --prefix src/voice_bridge_debug/frontend ci
	@npm --prefix src/voice_bridge_debug/frontend run build
	@git diff --exit-code -- src/voice_bridge_debug/voice_bridge_debug/frontend_dist
