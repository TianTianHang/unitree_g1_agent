# TextOp Direct Runtime Hardening Implementation Plan

> 历史计划：其中把 TextOp 依赖同步到 `.venv-ros` 的方案已废止。当前入口和环境所有权见
> [`docs/project_governance.md`](../../project_governance.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让内置 TextOp 推理在项目自有环境中离线、可复现地运行，并关闭 review 发现的四个部署缺口。

**Architecture:** 依赖由 uv 的 `textop` group 管理；全部模型文件由 manifest 校验；模型结构由仓库常量定义；generator runtime 只接收实际需要的 checkpoint、VAE、normalization 和 CLIP 文件。

**Tech Stack:** Python 3.10、uv、PyTorch CUDA、OpenAI CLIP、ROS 2 Humble、pytest、YAML manifest。

## Global Constraints

- 推理固定使用 `cuda:3`。
- 不安装或导入 RobotMDAR package/wheel。
- 运行时不下载代码或模型。
- backend 只能启动前静态选择，不允许 fallback。
- 每项行为改动先写失败测试，再做最小实现。

---

### Task 1: 收紧 generator manifest 与 runtime 接口

**Files:**
- Modify: `src/textop_backend/textop_backend/manifest.py`
- Modify: `src/textop_backend/textop_backend/robotmdar_runtime.py`
- Modify: `src/textop_backend/textop_backend/generator_node.py`
- Modify: `src/textop_backend/launch/textop_backend.launch.py`
- Modify: `src/textop_backend/config/textop_generator.yaml`
- Test: `src/textop_backend/tests/test_manifest.py`
- Test: `src/textop_backend/tests/test_direct_textop_inference.py`

**Interfaces:**
- `GeneratorManifest` 产生 `checkpoint`、`vae`、`normalization`、`clip` 四个 `AssetManifest`。
- `RobotMDARRuntime(..., vae, normalization, clip_weights, device, guidance_scale, compile_backend)` 不再接收 `statistics` 或 `skeleton_asset_root`。

- [ ] 写 manifest 必须包含 `generator.clip` 且不再要求 `statistics` 的失败测试。
- [ ] 写 runtime 不读取 Hydra YAML、CLIP 只接受本地权重路径、launch 不暴露 skeleton 参数的失败测试。
- [ ] 运行定向测试确认按预期失败。
- [ ] 实现固定模型配置、离线 CLIP 加载和接口清理。
- [ ] 运行定向测试确认通过。
- [ ] 提交 `fix: harden textop runtime artifacts`。

### Task 2: 建立项目 TextOp 依赖环境

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `Makefile`
- Test: `tests/test_textop_env_check.py` 或现有环境检查测试。

**Interfaces:**
- uv group `textop` 固定声明 Torch、CLIP、einops 和 GPU ONNX Runtime。
- uv group `textop_cudnn8` 固定声明 Tracker ORT 所需的 cuDNN 8，并与 Torch groups 互斥。
- `make bootstrap-textop` 将主 group 同步进 `.venv-ros`，将 cuDNN 8 同步进项目
  `.unitree/textop-cudnn8-venv`。

- [ ] 写依赖 group 与 Makefile 命令的结构测试并确认失败。
- [ ] 增加最小依赖声明和 bootstrap target。
- [ ] 运行 `uv lock` 和定向测试。
- [ ] 使用 uv 将 textop group 安装到项目 Python 3.10 环境。
- [ ] 创建真实 CUDA ONNX session，确认 cuDNN 8 预加载后不回退 CPU。
- [ ] 提交 `build: add project textop runtime dependencies`。

### Task 3: 下载 CLIP 制品并完成 GPU3 验收

**Files:**
- Modify: `src/textop_backend/config/textop_pretrained.yaml`
- Modify: `docs/textop_runtime_acceptance.md`

**Interfaces:**
- manifest 的 `generator.clip` 指向本地 ViT-B/32 文件并记录 SHA-256。

- [ ] 使用获准的网络访问下载 CLIP ViT-B/32 到稳定的本地模型目录。
- [ ] 计算 SHA-256 并更新 manifest。
- [ ] 使用项目 `.venv-ros` 在 GPU 3 完成 manifest 校验、文本编码和 `[8,29]` primitive smoke。
- [ ] 运行 TextOp 全量测试、compileall、静态扫描和 diff 检查。
- [ ] 提交 `test: verify offline textop gpu runtime`。
