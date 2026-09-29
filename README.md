# 科研创新分析器

`research-model-innovation` 是面向科学机器学习研究的 Codex Skill，从项目代码出发，形成有文献依据、可追溯、可实验检验的模型创新方案。

## 工作流程

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
evals/            离线科研任务样本（合成资料）
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

模型比较支持本地传递依赖、外部辅助函数变化以及两个指定模型的直接比较。未核验的依赖会明确标记，不将类源码未变等同于模型行为等价。

支持自定义 `--import-root` 分析 src 布局，并展开可解析的本地单继承组件。结果导入核对完整 task × required metric × seed，能识别整个任务或指标都未提交的情况。配置校验区分缺失、unknown、类型错误及明确停用；数据计划缺失/冲突不会被当作协议已确认。详见 [协议规范](references/protocol_contract.md)。

组件证据保留条件分支及赋值来源。manifest 单独检查源码冻结覆盖与关键依赖，few-shot 清单核对类别和 N-way/K-shot/query/episode 数量。可选的 [配对统计](references/statistical_decisions.md) 按预声明阈值给出探索性区间，证据不足时保持未判定。

[参数追踪](references/config_flow.md) 不执行项目；另附 assets/verify_instance.py 供用户在审阅后的环境自行核验实例。该脚本会导入用户选定的工厂，不属于 Codex 自动静态检查流程。

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
