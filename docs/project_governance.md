# 项目治理基线

本文定义当前仓库的工程门禁、TextOp 功能冻结和解冻条件。架构设计文档描述系统应该怎样
工作；本文描述什么条件下允许继续扩张代码。

## 当前决策

TextOp 进入功能冻结期。冻结不禁止缺陷修复、测试补齐、可移植性修复、文档修正和安全性
增强，但禁止增加新的模型系列、推理 provider、运行时 backend 切换、自动降级路径或新的
GPU 组合。

解除冻结必须同时满足：

1. 普通 CI 的 build、test、integration、frontend、lint 和 `check-textop-core` 连续通过；
2. `make check-textop` 在目标 GPU 主机通过，并记录环境与制品摘要；
3. TextOp 自研适配层纳入 Ruff 和 Pyright，不能用排除整个包的方式转绿；
4. `textop_model` 的来源、许可证和本地修改基线完成核验；
5. GPU smoke、Tracker provider smoke 和真机停止策略有最近一次验收记录。

## 环境所有权

| 环境 | 用途 | 允许的依赖组 |
| --- | --- | --- |
| `.venv-ros` | 构建、普通测试、lint、调试面板 | 默认组；可显式切换到 ASR 组 |
| `.venv-textop` | TextOp generator/tracker、GPU 测试 | `textop` |
| `.unitree/textop-cudnn8-venv` | 仅提供 ORT 所需 cuDNN 8 动态库 | `textop_cudnn8` |

禁止把 TextOp 依赖同步到 `.venv-ros`，也禁止节点引用相邻 checkout 的虚拟环境。

## 质量门禁

- `make test`：所有普通 ROS 包及 TextOp 轻量测试、低层守卫测试；
- `make test-integration`：强类型控制链 ROS launch 测试；
- `make lint`：自研 Python 源码的 Ruff 与 Pyright；
- `make check-textop-core`：普通 CI 可运行的 TextOp 测试和静态检查；
- `make check-textop`：独立推理环境中的 TextOp 完整包测试与静态检查；
- `make frontend`：前端锁定安装、构建及生成文件一致性。

`textop_model` 是上游派生的推理实现边界，暂不应用仓库的风格规则，但仍被语法编译、导入
路径测试和 TextOp 运行时测试间接覆盖。排除只允许精确到该目录，不能扩大到
`textop_backend` 的其他文件。

## 变更规则

涉及控制链、安全门、lease、模型 ABI、环境或模型制品的变更必须同步更新对应契约文档和
测试。提交应按环境与门禁、第三方边界、文档治理等独立关注点组织；不得把模型更新、运行时
行为改变和纯格式化混在同一个提交中。

硬件不可用时，GPU 或实机条目必须明确记为“未执行”，不能用 CPU fallback 代替通过。
