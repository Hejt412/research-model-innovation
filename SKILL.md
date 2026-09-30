---
name: research-model-innovation
description: "Analyze scientific ML codebases, find transferable mechanisms in recent cross-domain papers, verify same-field prior art, and design single-variable model innovations. Use for 科研创新、模型创新分析、跨领域机制迁移、同领域查新 or code-level research improvement plans, not routine debugging or general paper summaries."
---

# 科研创新分析器

从项目代码和研究证据出发，形成可追溯、可执行、可证伪的单项创新方案。默认使用用户语言，准确保留论文题名和技术符号。按请求推进连续工作流，不自动创建独立 Agent。

## 核心约束

- 先确定真实 baseline 和 Innovation Gap Map，再搜索机制。脚本仅提供静态索引，不导入项目、不执行 forward、不测真实参数/FLOPs。项目不足时可做局部分析，不能把示例当作用户事实。
- 默认优先有证据支持的模型结构创新：表示、交互/融合、拓扑、路由或状态更新。用户指定其他方向时遵循其要求。扩容、堆模块、换 backbone 或名称本身不证明创新；没有合格结构候选时说明补证和备选，不强推。
- 区分【代码事实】【文献事实】【推断】【研究假设】【待验证】。论文/DOI/公式/API/结果须可核实；查新不足为 Unknown，不能用 Green 或输出形状正确暗示新颖性、机制因果或收益。
- 不启动训练、微调、训练式 profiling、超参数搜索或真实模型核验；交付用户运行的脚本、配置和 cmd.exe / Anaconda Prompt 命令。未知入口的 import、--help、dry-run 都不自动安全。
- 每个实验相对明确对照只改变一个独立因素。结构实验默认冻结 loss、训练和数据协议；模块名不能掩盖多个变化。分析请求交付方案，要求实现时按已有授权修改一个因素、优先现有文件。
- 保持证据链：代码位置 → 缺口 → 迁移机制/条件 → 同领域先例/实质差异 → 数学及接口 → 单变量实验 → 用户结果。性能估计、设计核对、样本核验和真实研究结论分别记录。

## 按当前任务读取

| 当前工作 | 所需规范 |
|---|---|
| 理解架构/定位缺口 | [项目工作流](references/research_workflow.md)、[缺口验证](references/gap_validation.md)；需要工具时读 [静态脚本](references/script_usage.md)，参数疑点读 [配置传递](references/config_flow.md) |
| 文献发现/查新/选择候选 | [检索规则](references/paper_search_policy.md)、[创新评估](references/innovation_evaluation.md)；有账本时按 [证据工具](references/evidence_tools.md) 去重和增量检索 |
| 深入结构设计/实现 | [结构设计](references/structural_design.md)、[实验规则](references/experiment_rules.md)；实现与用户核验请求另读 [核验契约](references/structure_probe.md)，冻结实验时读 [协议规范](references/protocol_contract.md) |
| 复核已有结果/历史记录 | [证据工具](references/evidence_tools.md)、[运行来源](references/run_provenance.md)；统计判定读 [配对统计](references/statistical_decisions.md)，旧记录读 [版本迁移](references/record_versions.md) |
| 交付/维护本 Skill | [输出规范](references/output_format.md)；维护时运行 tests/，按 [行为验收](references/behavioral_acceptance.md) 复核并用 [版本对应](references/behavior_versions.md) 冻结来源、规划受影响案例 |

只加载当前任务所需规范。架构局部请求无需展开结果来源、统计或记录迁移；必要前置证据仍须核实。

## 工作流

1. 阅读项目指令、README、已有档案/历史与真实模型、数据、训练、评估入口。确认扫描范围、工厂参数传递、条件分支和有效配置，不能靠文件名或最后一次赋值猜实际组件。历史结果对照当时源码/依赖，无法对应时保留归因未知。形成有代码定位、竞争解释、最小诊断和可证伪问题的 Gap Map；concat 本身不证明交互不足。
2. 由缺口抽象问题生成跨领域检索式，优先过去12个月，不足扩至24/36个月，用户窗口优先。同领域查新移除领域排除词，包含早期概念等价先例。打开原始方法，记录日期、query、访问范围和页/节/式；仅摘要作为线索。
3. 候选先通过证据、迁移条件、推理信息、接口和预算筛选，再优先结构。多个合格结构按缺口匹配、迁移依据、风险及成本取舍，说明未选原因和最小区分诊断；成本未知保留未知，不虚构收益分数或固定候选数。查新风险附最接近先例及覆盖限制。新参数化需要重新估算预算，不能沿用旧方案百分比。
4. 选一个因素深入：原/新数据流、轴/形状、完整公式、实际文件/类/接口、初始化与 baseline 禁用路径、机制观测/否定条件及相关对照。沿完整 forward 到任务实际预测量，审查改动能否被原可训练层吸收、最终预测是否仍为各分支函数之和；局部跨分支路径不能单独证明联合依赖。静态检查初始化梯度路径，区分前向成立与可学习性；需要数值或梯度诊断时另给用户运行方案。不能假定不存在的底层 API。结构核验由用户运行，合法零初始化不必让输出不同。
5. 给出 E0/E1、冻结项、实际入口/配置/cmd 与结果依赖；manifest 核对声明范围、源码覆盖及 task × metric × seed 和数据/episode 计划。仅当用户返回结果时加载结果复核规范，核对真实运行、单位、配对 seed 与协议后追加历史；可选创新元数据关联已知机制四维身份、G/I/H 和 E/manifest，未检索的 P 保持空并声明文献待查，不补造 ID。相同证据换安装来源或移动产物位置不重复回流，证据或机制修订追加。混杂、缺失和负结果保留，不凭文件名或相同 seed 推断独立训练/同采样。

报告开头先给推荐结构及实质差异、最大未知和下一步。仅输出请求适用的内容；完整研究再按 [报告模板](assets/research_report_template.md) 展开。项目档案/历史仅保存在实际项目，沿用 [档案](assets/research_profile_template.yaml) 与 [历史模板](assets/research_history_template.md)，不强制为内联回答建文件。已有失败机制只在新证据或协议变化时重提。
