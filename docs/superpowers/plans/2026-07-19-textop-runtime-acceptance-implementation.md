# TextOp Runtime Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints.

**Goal:** 将 TextOp runtime 从“代码可构造”推进到可复现部署、可诊断启动、GPU/ONNX smoke 可验收的 fail-closed 运行阶段。

**Architecture:** 保持 generator、tracker、low-level guard 三段式边界；generator 继续拥有 Action、stop/cancel、lease 生命周期，tracker 只消费 reference/odometry/lowstate 并发布 candidate，guard 是唯一真实 `/lowcmd` 发布者。运行环境通过项目自有 Python 3.10 环境和受 manifest/lock 管理的 inference artifact 提供，不从外部 TextOp checkout 导入。

**Tech Stack:** ROS 2 Humble、Python 3.10、ament_python、uv、PyTorch CUDA、ONNX Runtime、pytest、现有 `textop_backend` manifest/runtime adapters。

## Global Constraints

- backend 只能在启动前由 `motion_backend` 静态选择；运行时不切换、不自动 failover。
- generator 固定使用 `cuda:3`，禁止静默切 CPU 或其他 GPU。
- 实机 Tracker 配置必须包含 `CUDAExecutionProvider`，provider 不可用或发生回退时启动失败。
- 外部 `/home/ubuntu/Desktop/TextOp` checkout 只能阅读，不能出现在运行时 `PYTHONPATH`、editable install 或部署脚本中。
- 只有 `low_level_guard` 发布真实 `/lowcmd`。
- 每个任务遵循先写失败测试、确认失败、最小实现、确认通过、独立提交。

---

### Task 1: 运行时制品 manifest 与来源校验

**Files:**
- Modify: `src/textop_backend/textop_backend/runtime_preflight.py`
- Modify: `src/textop_backend/config/textop_generator.yaml`
- Test: `src/textop_backend/tests/test_runtime_preflight.py`
- Create: `src/textop_backend/config/textop_runtime_lock.yaml`

**Interfaces:**
- `RuntimeFacts` 增加 `robotmdar_digest: str | None`。
- `validate_generator_runtime(..., expected_robotmdar_version: str, expected_robotmdar_digest: str)` 校验版本和 digest。
- lock 文件包含 `robotmdar.version`、`robotmdar.source`、`robotmdar.sha256`，启动前读取并传入 preflight。

- [ ] 写测试：缺失 digest、版本不匹配、digest 不匹配均抛出 `PreflightError`；合法 lock 通过。
- [ ] 运行 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/textop_backend python3 -m pytest -q src/textop_backend/tests/test_runtime_preflight.py`，确认新增测试先失败。
- [ ] 实现分发 metadata/digest 探测；禁止从 `TextOp` checkout 推导 digest 作为通过条件。
- [ ] 重新运行同一测试，确认通过。
- [ ] 提交 `feat: validate textop runtime artifact lock`。

### Task 2: 项目 Python 环境与构建入口

**Files:**
- Modify: `pyproject.toml`
- Modify: `Makefile`
- Create: `scripts/textop_env_check.py`
- Test: `tests/test_textop_env_check.py`

**Interfaces:**
- 新增 `dependency-groups.textop`，只声明项目锁定的 runtime 包或内部 wheel，不声明外部 checkout 路径。
- `make bootstrap-textop` 创建/同步 `.venv-ros`；`make build-textop` 在该解释器下执行 ROS 构建。
- `scripts/textop_env_check.py` 输出 JSON 风格检查结果并以非零状态表示失败。

- [ ] 写测试：脚本拒绝 Python 3.11、错误解释器、外部 `robotmdar` origin；接受 Python 3.10 + lock 元数据。
- [ ] 运行测试确认先失败。
- [ ] 实现 Makefile target 和环境检查脚本；不修改全局 shell 配置。
- [ ] 运行脚本单元测试与 `make -n bootstrap-textop build-textop`，确认命令使用 `.venv-ros/bin/python`。
- [ ] 提交 `build: add reproducible textop runtime entrypoints`。

### Task 3: 启动图与 graph smoke

**Files:**
- Create: `src/g1_system_tests/test/test_textop_launch_graph.py`
- Modify: `src/g1_bringup/launch/g1_system.launch.py`（仅在测试暴露缺口时）
- Modify: `src/textop_backend/launch/textop_backend.launch.py`（仅在测试暴露缺口时）

**Interfaces:**
- 测试解析 launch 描述或使用 `ros2 launch` dry-run，断言 textop/official_loco 节点集合和 `/lowcmd` publisher 集合。

- [ ] 写 textop 与 official_loco 两组 graph 断言。
- [ ] 运行测试确认拓扑断言先失败或暴露现有差异。
- [ ] 修正最小 launch/config 缺口。
- [ ] 运行 graph smoke 与现有 launch 测试。
- [ ] 提交 `test: assert static textop launch topology`。

### Task 4: GPU primitive 与 ONNX ABI smoke

**Files:**
- Create: `src/textop_backend/tests/test_gpu_smoke.py`
- Create: `scripts/textop_gpu_smoke.py`
- Modify: `docs/textop_runtime_acceptance.md`

**Interfaces:**
- GPU smoke 固定读取 manifest，调用 `RobotMDARRuntime` 生成一个 primitive，断言 device=`cuda:3`、shape=`[8,29]`、数值 finite。
- Tracker smoke 使用 `load_onnx_policy`，断言 `[1,431] -> [1,29]` 和 active provider。

- [ ] 写可跳过但不可伪造通过的硬件测试；无 GPU/无 CUDA provider 时明确标记 skipped/failed 原因。
- [ ] 运行普通 CI，确认无硬件环境不会误报 pass。
- [ ] 实现 smoke CLI 和输出版本、GPU、manifest digest。
- [ ] 在 GPU3 环境执行一次实际 smoke 并保存日志。
- [ ] 提交 `test: add textop gpu and onnx smoke checks`。

### Task 5: 验收报告与回归验证

**Files:**
- Create: `docs/textop_runtime_acceptance_report.md`
- Modify: `docs/textop_runtime_acceptance.md`（勾选实际结果）

- [ ] 运行 TextOp 全量单元测试、包构建、graph smoke、环境检查。
- [ ] 记录代码提交、解释器、Torch/ORT/RobotMDAR 版本、GPU3 信息、制品 SHA-256 和未执行的实机项。
- [ ] 运行 `git diff --check`，确认工作树只包含本阶段变更。
- [ ] 提交 `docs: record textop runtime acceptance results`。

