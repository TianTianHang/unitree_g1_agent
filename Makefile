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
UNITREE_ROOT ?= $(COMMON_REPO_ROOT)/.unitree
UNITREE_SDK2_DIR ?= $(UNITREE_ROOT)/unitree_sdk2
UNITREE_SDK2_REPO ?= https://github.com/unitreerobotics/unitree_sdk2.git
UNITREE_SDK2_REF ?= 7740f8b67e386ab09c3b333187fd5f8582a75ddc
UNITREE_SDK2_BUILD_BASE ?= $(UNITREE_ROOT)/build/unitree_sdk2
UNITREE_SDK2_INSTALL_PREFIX ?= $(UNITREE_ROOT)/install/sdk2
UNITREE_ROS2_DIR ?= $(UNITREE_ROOT)/unitree_ros2
UNITREE_ROS2_REPO ?= https://github.com/unitreerobotics/unitree_ros2.git
UNITREE_ROS2_REF ?= 668d1ec5a05d1c38d3306bdca7d59f2ba3581a88
UNITREE_ROS2_BUILD_BASE ?= $(UNITREE_ROS2_WS)/build-foxy
UNITREE_ROS2_INSTALL_BASE ?= $(UNITREE_ROS2_WS)/install-foxy
UNITREE_ROS2_LOG_BASE ?= $(UNITREE_ROS2_WS)/log-foxy
FOXY_SETUP ?= /opt/ros/foxy/setup.bash
FOXY_UNITREE_SETUP ?= $(UNITREE_ROS2_INSTALL_BASE)/setup.bash
FOXY_BUILD_BASE := $(COMMON_REPO_ROOT)/build-foxy
FOXY_INSTALL_BASE := $(COMMON_REPO_ROOT)/install-foxy
FOXY_LOG_BASE := $(COMMON_REPO_ROOT)/log-foxy
FOXY_PYTEST_PATHS := \
	src/g1_agent_msgs/test \
	src/asr_node/tests \
	src/g1_interface/tests \
	src/g1_sim/tests \
	src/safety_control/tests \
	src/voice_bridge/tests
PYTEST_PATHS := \
	src/g1_agent_msgs/test \
	src/asr_node/tests \
	src/g1_interface/tests \
	src/g1_sim/tests \
	src/safety_control/tests \
	src/textop_backend/tests \
	src/voice_bridge/tests \
	src/voice_bridge_debug/tests
ROS_SETUP := source "$(FOXY_SETUP)"; \
	if [[ -f "$(FOXY_UNITREE_SETUP)" ]]; then \
		source "$(FOXY_UNITREE_SETUP)"; \
		export CMAKE_PREFIX_PATH="$(UNITREE_SDK2_INSTALL_PREFIX):$${CMAKE_PREFIX_PATH:-}"; \
		export LD_LIBRARY_PATH="$(UNITREE_SDK2_INSTALL_PREFIX)/lib:$${LD_LIBRARY_PATH:-}"; \
	else \
		echo "Unitree Foxy overlay not found; run 'make unitree-ros2-build'" >&2; \
		exit 1; \
	fi

export PYTHONNOUSERSITE := 1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD := 1
export UV_PROJECT_ENVIRONMENT := $(ROS_ENV)
export TEXTOP_CUDNN_LIB_DIR

.PHONY: bootstrap-env bootstrap bootstrap-asr bootstrap-textop-env bootstrap-textop build build-textop \
	test test-textop test-integration lint lint-textop check-textop-core check-textop frontend \
	unitree-source unitree-sdk2-source unitree-ros2-source unitree-sdk2-build unitree-ros2-build unitree-build \
	foxy-build foxy-test-core foxy-test-integration

unitree-sdk2-source:
	@mkdir -p "$(UNITREE_ROOT)"
	@if [[ ! -d "$(UNITREE_SDK2_DIR)/.git" ]]; then \
		git clone "$(UNITREE_SDK2_REPO)" "$(UNITREE_SDK2_DIR)"; \
	fi
	@git -C "$(UNITREE_SDK2_DIR)" remote set-url origin "$(UNITREE_SDK2_REPO)"
	@if ! git -C "$(UNITREE_SDK2_DIR)" cat-file -e "$(UNITREE_SDK2_REF)^{commit}"; then \
		git -C "$(UNITREE_SDK2_DIR)" fetch --depth=1 origin "$(UNITREE_SDK2_REF)"; \
	fi
	@git -C "$(UNITREE_SDK2_DIR)" checkout --detach "$(UNITREE_SDK2_REF)"

unitree-ros2-source:
	@mkdir -p "$(UNITREE_ROOT)"
	@if [[ ! -d "$(UNITREE_ROS2_DIR)/.git" ]]; then \
		git clone "$(UNITREE_ROS2_REPO)" "$(UNITREE_ROS2_DIR)"; \
	fi
	@git -C "$(UNITREE_ROS2_DIR)" remote set-url origin "$(UNITREE_ROS2_REPO)"
	@if ! git -C "$(UNITREE_ROS2_DIR)" cat-file -e "$(UNITREE_ROS2_REF)^{commit}"; then \
		git -C "$(UNITREE_ROS2_DIR)" fetch --depth=1 origin "$(UNITREE_ROS2_REF)"; \
	fi
	@git -C "$(UNITREE_ROS2_DIR)" checkout --detach "$(UNITREE_ROS2_REF)"

unitree-source: unitree-sdk2-source unitree-ros2-source

unitree-sdk2-build: unitree-sdk2-source
	@cmake -S "$(UNITREE_SDK2_DIR)" -B "$(UNITREE_SDK2_BUILD_BASE)" \
		-DBUILD_EXAMPLES=OFF -DCMAKE_BUILD_TYPE=Release \
		-DCMAKE_INSTALL_PREFIX="$(UNITREE_SDK2_INSTALL_PREFIX)"
	@cmake --build "$(UNITREE_SDK2_BUILD_BASE)" --parallel
	@cmake --install "$(UNITREE_SDK2_BUILD_BASE)"

unitree-ros2-build: unitree-ros2-source
	@test -f "$(FOXY_SETUP)"
	@cd "$(UNITREE_ROS2_WS)"; source "$(FOXY_SETUP)"; \
		colcon --log-base "$(UNITREE_ROS2_LOG_BASE)" build --symlink-install \
			--build-base "$(UNITREE_ROS2_BUILD_BASE)" \
			--install-base "$(UNITREE_ROS2_INSTALL_BASE)" \
			--event-handlers console_direct+

unitree-build: unitree-sdk2-build unitree-ros2-build

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

build: foxy-build

test: foxy-test-core

test-integration: foxy-test-integration

# ROS 2 Foxy is kept in a separate colcon overlay and Python 3.8 process.
# Do not reuse the TextOp Python 3.10 environment here.
foxy-build: unitree-build
	@test -f "$(FOXY_SETUP)"
	@test -f "$(FOXY_UNITREE_SETUP)"
	@source "$(FOXY_SETUP)"; source "$(FOXY_UNITREE_SETUP)"; \
		test "$$(python3 -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))')" = "3.8"; \
		export CMAKE_PREFIX_PATH="$(UNITREE_SDK2_INSTALL_PREFIX):$${CMAKE_PREFIX_PATH:-}"; \
		export LD_LIBRARY_PATH="$(UNITREE_SDK2_INSTALL_PREFIX)/lib:$${LD_LIBRARY_PATH:-}"; \
		export RMW_IMPLEMENTATION=$${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}; \
		colcon --log-base "$(FOXY_LOG_BASE)" build --symlink-install \
			--build-base "$(FOXY_BUILD_BASE)" --install-base "$(FOXY_INSTALL_BASE)" \
			--event-handlers console_direct+

foxy-test-core: foxy-build
	@source "$(FOXY_SETUP)"; source "$(FOXY_UNITREE_SETUP)"; source "$(FOXY_INSTALL_BASE)/setup.bash"; \
		export RMW_IMPLEMENTATION=$${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}; set -e; \
		for test_path in $(FOXY_PYTEST_PATHS); do python3 -m pytest -q "$$test_path"; done
	@source "$(FOXY_SETUP)"; source "$(FOXY_UNITREE_SETUP)"; source "$(FOXY_INSTALL_BASE)/setup.bash"; \
		colcon --log-base "$(FOXY_LOG_BASE)" test \
			--build-base "$(FOXY_BUILD_BASE)" --install-base "$(FOXY_INSTALL_BASE)" \
			--packages-select low_level_guard --event-handlers console_direct+; \
		colcon test-result --test-result-base "$(FOXY_BUILD_BASE)/low_level_guard/test_results" --verbose

foxy-test-integration: foxy-build
	@source "$(FOXY_SETUP)"; source "$(FOXY_UNITREE_SETUP)"; source "$(FOXY_INSTALL_BASE)/setup.bash"; \
		export RMW_IMPLEMENTATION=$${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}; \
		if [[ -d "$(FOXY_BUILD_BASE)/g1_system_tests/test_results" ]]; then \
			find "$(FOXY_BUILD_BASE)/g1_system_tests/test_results" -type f -delete; \
		fi; \
		colcon --log-base "$(FOXY_LOG_BASE)" test \
			--build-base "$(FOXY_BUILD_BASE)" --install-base "$(FOXY_INSTALL_BASE)" \
			--packages-select g1_system_tests \
			--ctest-args -R typed_control_chain --event-handlers console_direct+; \
		colcon test-result --test-result-base "$(FOXY_BUILD_BASE)/g1_system_tests/test_results" --verbose

build-textop: build bootstrap-textop
	@$(ROS_SETUP); $(TEXTOP_ENV)/bin/python -m colcon build \
		--packages-select g1_agent_msgs textop_backend \
		--build-base $(TEXTOP_BUILD_BASE) --install-base $(TEXTOP_INSTALL_BASE) \
		--symlink-install --event-handlers console_direct+

lint: build bootstrap
	@$(ROS_SETUP); source install-foxy/setup.bash; $(UV_RUN) ruff check src
	@$(ROS_SETUP); source install-foxy/setup.bash; $(UV_RUN) pyright

test-textop: build-textop
	@$(ROS_SETUP); source install-foxy/setup.bash; source $(TEXTOP_INSTALL_BASE)/setup.bash; \
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
