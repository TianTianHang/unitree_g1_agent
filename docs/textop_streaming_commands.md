# TextOp 流式 Prompt 指令契约

TextOp 的控制输入定义为连续的 `(prompt, duration)` 指令流。新指令不需要等待旧指令的
duration 结束；系统在下一个 primitive 边界用新 prompt 替换旧 prompt，并保留生成 history、
absolute pelvis pose 和低层控制会话。

这里的“流式”指 Prompt 命令流，不是把语言模型 token 逐个输入 TextOp。

## 指令语义

每条指令至少包含：

- `request_id`：调用方生成的唯一 ID；
- `prompt`：非空动作文本；
- `duration`：该 prompt 最长有效时间，从指令被接受时重新计时；
- `backend_id`：必须为空或 `textop`。

任意时刻只有一条活动 Prompt 指令：

1. 空闲时，新指令启动连续控制会话；
2. 活动时，新指令原子替换旧指令；
3. 旧指令返回 `superseded_by:<new_request_id>`；
4. 已经在 GPU 中计算的旧 primitive 通过 generation 检查丢弃；
5. 切换发生在 primitive 边界，不在一个八帧 primitive 中间截断；
6. 非法新指令被拒绝，不能破坏仍然有效的旧指令；
7. stop/cancel 立即阻止新 reference/candidate，并撤销 lease；
8. duration 到期后生成 final primitive，等待 Tracker drain 后结束。

## 连续性边界

Prompt 替换必须保留 Generator 的 motion history 与 absolute pose。Tracker 在替换 reference
buffer 时保留上一帧 policy action；lease 可以更新 request ID，但连续 TextOp 会话中不得主动
释放后重新申请低层控制权。Guard 在 lease/candidate request ID 短暂不一致时继续 fail-closed。

最大正常替换延迟为一个 primitive。当前模型固定八帧、50 Hz，因此目标上限为 160 ms，
不包含新文本编码或 GPU 拥塞时间。

## 状态

```text
IDLE -> GENERATING -> EXECUTING -> DRAINING -> IDLE
                       |
                       +-- new prompt --> REPLACING --> GENERATING
                       +-- stop -------> STOPPING ----> IDLE
                       +-- fault ------> FAILED ------> IDLE
```

## 收口验收

- 单 prompt 按 duration 生成并完成；
- 执行中替换 prompt，旧结果不会发布；
- 连续快速更新时只有最新 generation 生效；
- 替换后 history、absolute pose、segment 和 Tracker previous action 连续；
- 非法替换不影响当前指令；
- 任意阶段 stop 都能撤销 lease；
- TextOp ROS 节点从独立 `install-textop` 和 `.venv-textop` 启动；
- launch 参数可真实加载，不能只通过纯逻辑单元测试。

Agent 接入不属于本阶段。后续 Agent 只负责产生 `prompt` 与 `duration`，不感知 primitive、
Tracker、lease、ONNX provider 或低层关节命令。

## 当前实现

Generator Action Server 使用单一后台流线程拥有模型状态、Session 和 lease。每个
`ExecuteMotion` goal 只提交命令并等待自己的 outcome：

- 新 goal 在下一个 primitive 边界激活；
- 旧 goal 以 `superseded_by:<request_id>` 结束；
- pending goal 被更新时立即标记为 superseded；
- Prompt 替换保留 Generator history/absolute pose 和 Tracker previous action；
- 新 reference 准备好之前不切换 lease request ID，避免文本编码期间主动制造控制空洞；
- stop 在文本编码或 primitive 推理期间使 generation 失效，迟到结果不会发布；
- cancel 已经 superseded 的旧 goal 不会停止当前新 goal。
