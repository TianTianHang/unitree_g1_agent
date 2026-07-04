# G1 Interface Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the `src/g1_interface` P0 implementation so sport API requests match Unitree ROS2 message definitions, unsafe command publication is blocked when state is unavailable/stale, and tests run from a local `.venv`.

**Architecture:** Keep ROS message imports at the node boundary and pure behavior in testable Python helpers. Update fake test messages to match real `unitree_api/msg/Request` and `Response` nesting. Keep changes scoped to `sport_api.py`, `node.py`, `config.py`, tests, and local test tooling.

**Tech Stack:** Python 3.11, pytest, PyYAML, ROS2 `unitree_api` message shape.

## Global Constraints

- Do not modify unrelated user changes in `.gitignore`.
- Use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface .venv/bin/python -m pytest` for verification.
- Do not commit unless explicitly requested.
- Production behavior changes require a failing test first.

---

### Task 1: Local Python Test Environment

**Files:**
- No tracked file changes required.

**Interfaces:**
- Consumes: project root `.gitignore` entry for `.venv`.
- Produces: `.venv/bin/python` and `.venv/bin/pytest`.

- [x] **Step 1: Verify `.venv` is ignored**

Run: `sed -n '1,220p' .gitignore`
Expected: output includes `.venv`.

- [x] **Step 2: Create the virtual environment and install test dependencies**

Run: `python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip pytest PyYAML`
Expected: command exits 0.

### Task 2: Unitree Sport API Message Shape

**Files:**
- Modify: `src/g1_interface/tests/test_sport_api.py`
- Modify: `src/g1_interface/g1_interface/sport_api.py`

**Interfaces:**
- Produces: `SportApiClient.build_request()` populates `request.header.identity.id`, `request.header.identity.api_id`, and string `request.parameter`.
- Produces: `SportApiClient.record_response()` reads `response.header.identity.id`, `response.header.identity.api_id`, and `response.header.status.code`.

- [x] **Step 1: Write failing tests**

Add nested fake request/response classes matching `unitree_api/msg/Request` and `Response`.

- [x] **Step 2: Run focused test to verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface .venv/bin/python -m pytest src/g1_interface/tests/test_sport_api.py -q`
Expected: FAIL because `SportApiClient` still writes flat fields and bytes.

- [x] **Step 3: Implement minimal nested-message support**

Set request identity fields through `header.identity`, keep pending map keyed by identity id, and set `parameter` to a JSON string.

- [x] **Step 4: Verify focused test passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface .venv/bin/python -m pytest src/g1_interface/tests/test_sport_api.py -q`
Expected: PASS.

### Task 3: Safe Command Admission and Callback Robustness

**Files:**
- Modify: `src/g1_interface/tests/test_node_helpers.py`
- Modify: `src/g1_interface/g1_interface/node.py`

**Interfaces:**
- Produces: `check_sport_command_allowed(now_sec, last_lowstate_sec, state_timeout_sec) -> tuple[bool, str | None]`.
- Produces: callbacks log and drop malformed or stale commands instead of throwing or publishing.

- [x] **Step 1: Write failing helper tests**

Add tests for no lowstate, stale lowstate, fresh lowstate, malformed safe command parsing, and unsafe numeric loco values.

- [x] **Step 2: Run focused test to verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface .venv/bin/python -m pytest src/g1_interface/tests/test_node_helpers.py -q`
Expected: FAIL because admission helper and numeric limits are missing.

- [x] **Step 3: Implement minimal helper and callback usage**

Add bounded parsing and a shared `_publish_sport_command()` callback path that catches parse/build errors and checks lowstate freshness before publish.

- [x] **Step 4: Verify focused test passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface .venv/bin/python -m pytest src/g1_interface/tests/test_node_helpers.py -q`
Expected: PASS.

### Task 4: Config Validation Coverage

**Files:**
- Modify: `src/g1_interface/tests/test_config.py`
- Modify: `src/g1_interface/g1_interface/config.py`

**Interfaces:**
- Produces: `G1InterfaceConfig.validate()` rejects missing/empty runtime-required topics, missing timeouts, and missing `set_velocity` API ID.

- [x] **Step 1: Write failing config tests**

Add tests proving empty `low_state_low_freq`, empty `secondary_imu`, and missing `set_velocity` are rejected.

- [x] **Step 2: Run focused test to verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface .venv/bin/python -m pytest src/g1_interface/tests/test_config.py -q`
Expected: FAIL because validation is incomplete.

- [x] **Step 3: Implement validation**

Extend required topics and required numeric keys.

- [x] **Step 4: Verify focused test passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface .venv/bin/python -m pytest src/g1_interface/tests/test_config.py -q`
Expected: PASS.

### Task 5: Full Verification

**Files:**
- No additional source changes expected.

**Interfaces:**
- Consumes: all tests.
- Produces: verified repair status.

- [x] **Step 1: Run all tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface .venv/bin/python -m pytest src/g1_interface/tests -q`
Expected: PASS.

- [x] **Step 2: Inspect git diff**

Run: `git diff -- src/g1_interface docs/superpowers/plans/2026-07-04-g1-interface-repair.md`
Expected: only scoped repair changes.
