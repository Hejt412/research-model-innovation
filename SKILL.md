---
name: research-model-innovation
description: "Analyze scientific ML codebases, find transferable mechanisms in recent cross-domain papers, verify same-field prior art, and design single-variable model innovations. Use for 科研创新、模型创新分析、跨领域机制迁移、同领域查新 or code-level research improvement plans, not routine debugging or general paper summaries."
---

# 科研创新分析器

从项目证据出发，形成可追溯的创新候选和一个可执行、可证伪的单变量方案。默认用用户语言输出；技术符号和原始论文题名保持准确。使用一个连续工作流，无需自动创建独立 Agent。

## 必须遵守

- 先理解代码、确定 baseline、建立 Innovation Gap Map，再搜索创新。无项目时索取路径或关键文件；可先交付输入清单，不能把示例项目当成用户事实。
- 区分【代码事实】【文献事实】【推断】【研究假设】【待验证】。推测的缺陷不得写成已证实瓶颈；从未运行的结果不得写成性能提升。
- 每个候选的证据链为：代码位置 → 缺口/证据 → 跨领域机制 → 可迁移条件 → 本领域先例 → 实质差异 → 数学及接口设计 → 单变量实验 → 用户提供的结果。
- 不启动任何训练、微调、训练式 profiling 或超参数搜索，也不以 smoke test 名义跑训练。提供脚本、配置、命令和简短执行说明，交给用户运行。Windows 命令必须兼容 cmd.exe / Anaconda Prompt。
- 每个实验相对其明确的对照只改变一个独立因素。一个命名模块若同时改变结构与损失，仍是两个因素。组合必须在独立验证后另列实验。
- 论文、DOI、公式来源、API 和实验结果必须可核实。检索覆盖不足时标记 Unknown，不能用 Green 暗示已经查新。
- 分析请求交付方案；用户要求实现时按已有授权修改一个因素，优先现有文件，不额外要求确认。不得把分析 Skill 视为改动整个训练流程的授权。

## 阶段 1：项目理解与缺口定位

读取项目指令、README、现有 `research_profile.yaml` 和 `research_history.md`，再阅读模型、数据、训练及评估入口。按 [项目工作流](references/research_workflow.md) 确认 baseline 和实验协议，追踪 forward、损失及数据划分。多个候选 baseline 不明确时列出证据并询问必要信息，继续不依赖 baseline 的盘点。

可用 [静态分析脚本](references/script_usage.md) 提取源码定位；这些脚本不导入项目、不执行 forward、不统计真实参数量。脚本输出是阅读索引，不是模型结构的完整证明。

输出模型比较及 Innovation Gap Map：模块、现有实现、代码证据、潜在问题、已有实验证据、可证伪问题。按 [缺口优先级与机制验证](references/gap_validation.md) 区分已观测问题与结构猜测，优先补最小诊断证据。暂不填入随意推荐的模块。不同模型可显式选择比较；类源码未变不代表依赖或模型行为未变。

## 阶段 2：跨领域发现与机制迁移

按 [文献检索规则](references/paper_search_policy.md)，以缺口的抽象问题生成检索式。默认优先过去 12 个月，不足再扩展至 24/36 个月，窗口相对实际检索日；用户指定窗口优先。本轮排除本项目应用领域，优先适合问题的顶刊原始研究。

打开原始来源核对元数据和方法，记录检索日期、检索式、可访问范围与证据位置。为有机制对应关系的论文填写 [创新卡](assets/innovation_card_template.md)，说明原问题 → 抽象问题 → 当前问题，以及不可迁移的条件。无法访问方法正文的文献只列为线索。

已有文献时先检查结构化账本，使用 [证据与实验工具](references/evidence_tools.md) 去重、保留版本关系、检查主张来源，再按缺口增量检索。工具不联网认证论文，不把来源关联当作结论已验证。

## 阶段 3：同领域先例与创新风险

移除跨领域检索的领域排除词，对每个机制搜索本领域概念同义词、数学实现、模块变体和引用链。查新不受跨领域的 36 个月窗口限制，必须包括较早的先例。

按 [创新评估规则](references/innovation_evaluation.md) 比较机制、任务、数据协议、监督假设和实现位置；给出 Green/Yellow/Orange/Red 或证据不足的 Unknown，并附最接近先例与覆盖限制。不能仅因换 backbone、换名称或拼接模块就主张新颖性。

## 阶段 4：单项创新工程化

综合证据、适配性、重复风险、可检验性及成本排序；默认深入一个证据最充分的候选，若无候选满足条件，明确证据缺口而不强推。

提供前后数据流、张量形状、定义完整的数学公式、文件/类/函数、真实依赖接口、伪代码或请求范围内的代码。示意公式须标明为新方案；库未提供的参数不能写成现成 API，例如不能假定 Mamba 接受 `state_bias`。说明需修改的底层实现、稳定性约束、初始化和 baseline 等价的禁用路径。

按 [实验规则](references/experiment_rules.md) 给出 E0 与 E1、冻结配置、用户运行命令、判定标准及消融。检查实现时限于静态检查及确认不会触发训练的测试，不加载未知训练入口。参数/FLOPs/性能未测即写待测。

用实验 manifest 保存经核对的有效配置和源码指纹；对照检查只标出声明范围内外的变化，不能自动证明单变量。需要机制归因时增加容量/计算量匹配的替代对照。用户返回结果后，核验配置指纹、单位和配对 seed，导入观测并追加研究历史；混杂、缺失或负结果也保留。

## 报告与连续研究

按 [输出格式](references/output_format.md) 和 [报告模板](assets/research_report_template.md) 交付。完整分析使用全部章节；仅架构分析等局部请求只输出适用章节，明确其余未执行，不强制越过用户范围。

项目研究记录使用 [历史模板](assets/research_history_template.md)，仅在实际项目保存。保留历史条目，按日期追加；未跑实验为 proposed/implemented，不得写成 validated。发现已失败/已否决的相同机制时优先解释，只有新证据或协议变化才重提。配置可采用 [项目档案模板](assets/research_profile_template.yaml)，不把轴承、Mamba 或任何数据集写成所有项目的默认事实。

维护本 Skill 时运行仓库 `tests/`，并按 [科研任务验收](references/behavioral_acceptance.md) 检查行为。案例结果只说明测试场景中的表现，不替代真实课题验证。
