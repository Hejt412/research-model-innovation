# 科研创新分析器

`research-model-innovation` 是面向科学机器学习研究的 Codex Skill，从项目代码出发，形成有文献依据、可追溯、可实验检验的模型创新方案。

默认优先模型结构创新，例如表示构建、信息交互/融合、连接拓扑、路由和状态更新机制。候选仍须有问题证据和可迁移依据；结构实验默认冻结 loss、训练策略和数据协议。无合格结构候选时说明补证方向及非结构备选，用户明确指定其他创新方向时按其要求执行。

[结构设计规范](references/structural_design.md) 集中核对张量轴、连接、推理信息、状态和底层接口，关联项目资源预算、机制中间观测与消融。附用户运行的结构核验入口/spec，检查导出的形状、有限值及禁用后与 baseline 的样本数值一致性；项目适配模块需按真实接口编写，Codex 不执行目标模型。另有四个合成行为验收案例检验结构优先、不可行候选、用户方向和预算约束。

[核验契约](references/structure_probe.md) 新增原始导出值归档、离线复算、误差定位、源码前后摘要与实验关联。spec1兼容，spec2按任务声明分支执行、门控及状态关系；合法零初始化、非因果或跨样本模型不强加不适用性质。另有自主生成结构、概念等价先例和具体参数化预算三个合成验收案例。入口按请求加载规范，报告先给决策和下一步。

## 工作流程

初始化审查进一步核对梯度路径，识别双零低秩因子、冻结/断开或饱和门控等风险；必要诊断由用户单独运行。多个合格结构按问题证据、资源和可区分诊断取舍。结果回流可附 [创新关联元数据](assets/innovation_metadata_template.json)，将机制四维身份和 G/P/I/H 与 E/manifest 关联；缺失保持未知。

结构分析追踪完整预测函数，区分可被原层吸收、仍按分支可分离和真正新增联合依赖；局部交叉连接不直接等于任务交互。元数据格式2允许已知机制与实验先关联、文献 ID 待查，旧格式1仍严格读取。历史导入用独立稳定身份，安装来源和纯产物位置变化不重复追加，实际脚本、机制或证据修订仍保留。

[行为版本工具](references/behavior_versions.md)保存输入/规则快照与实际报告摘要，区分历史复核、当前来源匹配和需重跑。结构观测核验拒绝非零 JSON 下溢与非字符串键，并检查硬链接输出别名。上述工具不执行用户模型、训练或自动行为评测。

1. **理解项目与模型**：阅读模型、数据、训练和评估代码，确定 baseline，建立 Innovation Gap Map。
2. **跨领域发现**：围绕缺口检索近期其他领域的顶刊研究，提取可迁移的数学或架构机制。
3. **同领域查新**：搜索概念等价和相似实现，比较实质差异，评估创新重复风险。
4. **创新工程化**：给出一个创新点的结构、公式、代码位置、真实接口及单变量实验方案。

同时维护项目研究历史，避免反复推荐已经测试或否决的机制。适用于不同模态和模型，不限定 Mamba 或故障诊断。

## 安装

将本仓库放入 Codex 的个人技能目录，目录名保持为 `research-model-innovation`。如果已经安装，无需重复克隆。

Windows cmd.exe / Anaconda Prompt，默认技能目录示例：

```bat
git clone https://github.com/Hejt412/research-model-innovation.git "%USERPROFILE%\.codex\skills\research-model-innovation"
```

如果自定义了 `CODEX_HOME`，使用其下的 `skills` 目录。当前会话未发现新 Skill 时，可在新会话使用，或直接让 Codex 读取安装目录中的 `SKILL.md`。

## 使用

在实际研究项目中输入，替换为你的模型路径：

```text
$research-model-innovation

分析当前项目中的 FTFM.py，先理解 baseline 和已有创新，再定位研究缺口。
搜索最近两年不同领域顶刊中的可迁移机制，核验本领域较早及近期的相似工作。
给出一个创新点的结构、数学公式、代码修改位置和单变量实验方案。
不要启动训练；提供兼容 cmd.exe / Anaconda Prompt 的运行命令。
读取研究历史，避免重复推荐已经失败的机制。
```

分析请求交付方案；要求实现时按授权范围修改代码。项目档案和历史保存在各自研究项目中。

## 文件结构

```text
SKILL.md          核心流程与约束
agents/           中文显示名和默认调用提示
references/       项目分析、检索、创新评估、实验与输出规范
scripts/          模型分析、实验检查、结果回流与文献账本工具
assets/           报告、创新卡、文献表、项目档案与历史模板
tests/            标准库回归及命令行流程验收
evals/            合成任务、真实文献检索请求与行为复核摘要
```

脚本仅依赖 Python 3.12+ 标准库，不需要 PyTorch。使用方法见 [静态脚本说明](references/script_usage.md)。

| 脚本 | 用途 |
|---|---|
| `scan_project.py` | 盘点项目文件与角色线索 |
| `analyze_models.py` | 用 AST 定位模型候选、方法及模块赋值 |
| `compare_models.py` | 比较两份静态模型报告 |
| `extract_experiment_config.py` | 提取实验配置的源码证据 |
| `trace_config.py` | 对照明确工厂的参数传递、构造默认值与声明配置 |
| `experiment_manifest.py` | 冻结源码/有效配置，标出单变量声明以外的变化 |
| `import_results.py` | 导入用户 CSV，按 seed 配对、检查来源并追加历史 |
| `literature_ledger.py` | 文献去重、版本归组、主张证据检查及增量检索计划 |
| `data_protocol.py` | 核对样本/记录/设备划分和有序 support/query episode 清单 |
| `run_records.py` | 核对运行、权重/日志字节摘要、评估回执与原始结果，排查重复来源 |
| `record_versions.py` | 只读检查记录版本，创建保留原始字节的归档封套 |
| `behavior_records.py` | 冻结行为案例来源、登记人工复核、检查漂移并规划定向重跑 |

模型比较支持本地传递依赖、外部辅助函数变化以及两个指定模型的直接比较。未核验的依赖会明确标记，不将类源码未变等同于模型行为等价。

支持自定义 `--import-root` 分析 src 布局，并展开可解析的本地单继承组件。结果导入核对完整 task × required metric × seed，能识别整个任务或指标都未提交的情况。配置校验区分缺失、unknown、类型错误及明确停用；数据计划缺失/冲突不会被当作协议已确认。详见 [协议规范](references/protocol_contract.md)。

组件证据保留条件分支及赋值来源。manifest 单独检查源码冻结覆盖与关键依赖，few-shot 清单核对类别和 N-way/K-shot/query/episode 数量。可选的 [配对统计](references/statistical_decisions.md) 按预声明阈值给出探索性区间，证据不足时保持未判定。

[参数追踪](references/config_flow.md) 不执行项目；另附 assets/verify_instance.py 供用户在审阅后的环境自行核验实例。该脚本会导入用户选定的工厂，不属于 Codex 自动静态检查流程。

参数追踪对潜在副作用保留 unknown。统计判定还须关联 [真实运行来源](references/run_provenance.md)，不把不同 seed 或文件名当作独立训练证明。新实验记录分开保存 [格式、规则和工具版本](references/record_versions.md)，旧记录迁移保留原始字节及结果来源引用。

实验、结果及文献命令详见 [证据工具说明](references/evidence_tools.md)。缺口分析按观测证据分档，机制归因考虑容量/计算预算等竞争解释，见 [缺口优先级与机制验证](references/gap_validation.md)。

## 验证

```bat
python -X utf8 -m unittest discover -s tests -v
```

测试仅运行工具和处理合成记录，不执行样本项目或训练。完整科研行为验收方法见 [验收说明](references/behavioral_acceptance.md)。离线样本不能替代真实项目与联网文献检索验证。

GitHub Actions 在 Windows/Linux × Python 3.12/3.13 上执行同一套回归，工作流只运行 Skill 工具测试。查看 [CI 运行记录](https://github.com/Hejt412/research-model-innovation/actions/workflows/tests.yml)。真实私有项目验收材料与报告保存在用户本地，不随 Skill 发布。

## 研究约束

- 不自动启动训练、微调或超参数搜索；提供由用户执行的脚本、配置和命令。
- 每个实验相对明确对照只改变一个独立因素。
- 不虚构论文、DOI、接口、实验结果或首创结论。
- 静态脚本不执行项目代码，不能测出真实参数量、FLOPs 或性能。
- 文献检索需要可用的联网工具及原始来源；检索覆盖不足时标记 `Unknown`。
- 创新风险评级只描述本次检索范围内的重复风险，不保证论文发表或全球首创。
