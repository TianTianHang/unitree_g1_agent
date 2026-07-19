# TextOp Direct Runtime Hardening Design

> 历史设计：正式 TextOp 解释器现为独立 `.venv-textop`，不再是 `.venv-ros`。当前治理基线见
> [`docs/project_governance.md`](../../project_governance.md)。

## Goal

让本仓库内置的 TextOp 推理运行时可由项目自有 Python 3.10 环境离线、可复现地启动，
不依赖外部 RobotMDAR package、外部源码配置或运行时模型下载。

## Dependency boundary

在根 `pyproject.toml` 增加 `textop` dependency group，固定声明 generator 与 tracker 的
第三方运行依赖。推理源码继续直接位于 `src/textop_backend/textop_backend/textop_model`，
不会构建独立 inference wheel。`.venv-ros` 是正式运行解释器，外部 TextOp `.venv` 仅可
用于迁移期间对照，不是验收入口。

GPU 运行栈使用 CUDA 11.8。Generator 的 Torch/cuDNN 9 与 Tracker 所需 cuDNN 8 分别位于
主 `.venv-ros` 和独立 uv 锁定环境中；Tracker 显式预加载 cuDNN 8 后再创建 ONNX session。

## Artifact boundary

Generator manifest 只保留实际消费的四类制品：DAR checkpoint、VAE、57 维 normalization
和 CLIP ViT-B/32 权重。每个制品均要求路径存在且 SHA-256 匹配。删除未使用的
`statistics`；删除 runtime、node 和 launch 中未使用的 `skeleton_asset_root`。

CLIP 权重允许在部署准备阶段下载一次，但 generator 启动时只从 manifest 给出的本地文件
加载。运行时不得通过模型名称触发下载。

## Model configuration

当前模型结构与 checkpoint ABI 固定为 57 features、history 2、future 8、latent `[1,128]`、
5-step cosine diffusion，以及已记录的 VAE/denoiser 超参数。把这组配置写成本仓库常量，
runtime 不再读取 checkpoint 相邻的 `.hydra/config.yaml`。权重 key 与 tensor shape 必须严格
匹配本地模型，防止错误 checkpoint 被 `strict=False` 部分加载。

## Failure behavior

缺失依赖、CLIP 文件、制品 digest、CUDA 3 或权重 ABI 不匹配时启动失败。禁止联网补全、
CPU fallback、其他 GPU fallback、official loco failover 和运行时 backend 切换。

## Verification

- 单元测试覆盖 manifest CLIP 制品、固定模型配置、离线 CLIP 路径和废弃参数移除。
- uv lock 与项目 `.venv-ros` 同步后，直接从项目解释器导入 Torch、CLIP、einops。
- GPU 3 实际加载所有 generator 制品，完成文本编码与 `[8,29]` primitive smoke。
- 完整测试、compileall、静态 import 扫描和 `git diff --check` 通过。
