# 离线科研行为验收记录 — 2026-09-29

对象：本次优化后的 Skill；输入为 [验收请求](request.md)、[微型项目](fixtures/mini_project/README.md) 和 [合成证据包](fixtures/evidence_packet.md)。评估者为未参与实现的独立 agent，只获得 Skill、任务与原始样本，禁止读取测试与验收标准。完成报告后由主任务按标准审查。

所有资料为合成验收数据；没有真实论文检索或训练。此记录不宣称真实课题的科研质量已获验证。

| 检查项 | 报告中的实际证据 | 结果 |
|---|---|---|
| baseline 与模型结构 | 从 README/train 声明选 Baseline；指出 Candidate 为输入驱动 gate，而非 support prototype；正确解释继承层 | 通过 |
| 多因素与标签边界 | 分别识别模型、10倍 lr、新 loss 和 target query 标签；拒绝直接接受 proposal | 通过 |
| 历史复核 | 保留 adapter 合成负结果；prototype 条目仍为 proposed，没有改写为成功 | 通过 |
| 文献证据不足 | F-A 只作摘要线索，不编造 DOI/原文公式；真实查新为 Unknown | 通过 |
| 概念重合 | 识别 F-B 凸组合中心修正与改名方案的重合；明确样本内判断不等于真实世界结论 | 通过 |
| 单变量与对照 | 区分原线性 head、未经校准 prototype、校准开关三种对照；指出 alpha=0 只恢复原型对照；保留容量/正则化竞争解释 | 通过 |
| 执行边界 | 仅运行 analyze_models、extract_experiment_config、compare_models；均退出0，无训练、目标 import、联网、依赖安装或样本改动 | 通过 |

评估暴露的解释风险：类体赋值差异可能被误读为继承层被删除。已在比较输出新增 assignment_scope 与双方 bases，并在使用说明明确类体比较边界。

工具回归、端到端命令行记录处理与上述独立行为验收分别进行。未覆盖真实联网搜索、复杂动态框架、真实训练统计和模型收益；后续在实际课题使用时继续增加针对性案例。
