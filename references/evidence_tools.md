# 实验、结果与文献工具

所有命令为 Python 3.12+ 标准库程序。它们处理本地记录，不训练、不联网认证、不加载 checkpoint。命令中的路径均需替换；Windows 示例适用于 cmd.exe / Anaconda Prompt。

## 冻结实验与检查差异

先把实际入口、CLI 覆盖、配置继承核对后的有效设置整理为 JSON，可参考 [配置模板](../assets/effective_config_template.json)。模板中的 null 需补证，不能当有效实验设置。数据集、划分清单、代码版本等以用户核实的标识或摘要记录；脚本不会读取二进制数据验证身份。

```bat
set "SKILL_DIR=%USERPROFILE%\.codex\skills\research-model-innovation"
python "%SKILL_DIR%\scripts\experiment_manifest.py" snapshot "D:\research\project" --config "D:\research\records\effective-e0.json" --experiment-id E0 --out "D:\research\records\e0.json"
python "%SKILL_DIR%\scripts\experiment_manifest.py" snapshot "D:\research\project" --config "D:\research\records\effective-e1.json" --experiment-id E1 --control-id E0 --out "D:\research\records\e1.json"
python "%SKILL_DIR%\scripts\experiment_manifest.py" check "D:\research\records\e0.json" "D:\research\records\e1.json" --factor "启用条件模块" --allow-config /model/condition_adapter --allow-file models/model.py --out "D:\research\records\audit.json"
```

两个 snapshot 必须在各自真实源码状态下生成，不要对同一修改后的目录假称有旧快照。manifest 输出放被扫描项目之外。指纹使用 Python/文本配置的原始字节；空白改变也会提示审查。扫描范围/跳过项保留，不覆盖二进制、notebook 或运行时环境。配置中的 null 和空 seed 计划列入 unresolved_config_paths；存在这些未知项的结果不能视为协议已完整核验。未记录的配置字段无法自动发现，需按模板和实际训练入口核对。

`--allow-config` 是精确 JSON Pointer，可重复指定同一机制的必要配置项；列表整体比较。`--allow-file` 为精确相对路径，用 `/` 分隔。若配置文件也在项目内，需明确纳入文件变化声明。不得为了让检查通过，事后把额外 lr/loss 改动全部加进白名单。

退出码 0 表示生成成功/变化在声明范围内；检查发现额外变化或未发现变化时输出报告并退出 2。`within_declared_scope` 仍需读实际 diff：同一文件里可能存在多个因素。JSON manifest 含内容指纹，后续导入先验证指纹。

## 用户结果回流

CSV 格式参考 [结果表头](../assets/results_template.csv)。每行是一个实验 × seed × task × metric 的用户观测，必须包含单位和对应 manifest SHA-256。

`unit` 可以是 fraction、percent 或明确的其他单位；不自动换算，不把百分比增量误称相对提升。一个 task/metric 内单位必须一致。相同实验/seed/task/metric 重复、非有限数、未知实验和摘要不符会拒绝；缺失 seed 列明，不补值。相同 seed 只有在固定采样/协议一致时才构成有意义的配对。

```bat
python "%SKILL_DIR%\scripts\import_results.py" "D:\research\records\results.csv" --control "D:\research\records\e0.json" --experiment "D:\research\records\e1.json" --audit "D:\research\records\audit.json" --out "D:\research\records\summary.json" --history "D:\research\project\research_history.md"
```

输出逐 seed 配对、配对均值、差值及差值的样本标准差。按冻结配置的 training.seeds 检查计划，即使两组都漏掉同一 seed 也会报告；未提供 seed 计划时标记不完整。单 seed 不输出虚构方差；不自动计算未声明方法的 CI 或显著性。正差值不自动等于改善，按预先声明的指标方向/阈值解释。多任务分别统计，不能把多个任务或 query 伪装成独立训练 seed。

审查报告从 manifest 和原声明重新计算。混杂或缺失观测仍可归档，但标记 `incomplete_or_confounded`。历史条目按结果摘要指纹幂等追加，保留旧记录，状态为用户观测 evaluated，不表示 validated。历史默认不写，只有提供 `--history` 才追加。保留原 CSV、manifest、audit 和 summary 以便追溯。

## 文献账本

以 [空账本](../assets/literature_ledger_template.json) 开始。每次核验所得批次采用相同结构：

- papers：id、准确 title、authors 字符串列表、doi（可 null）、官方 url、version、access、checked_at（YYYY-MM-DD）；访问级别为 full_text/methods/abstract_only/metadata_only。
- claims：id、text、paper_id、kind（mechanism/metadata）、locator（章节/页/式等）。主张必须独立关联证据；源码事实保留在报告中。
- searches：date、stage（cross_domain/same_domain）、source、query，可额外记录窗口/排除词/纳入理由。

```bat
python "%SKILL_DIR%\scripts\literature_ledger.py" merge "D:\research\records\literature.json" "D:\research\records\new-papers.json" --out "D:\research\records\literature-next.json"
python "%SKILL_DIR%\scripts\literature_ledger.py" plan "D:\research\records\literature-next.json" --as-of 2026-09-29 --max-age-days 90 --out "D:\research\records\search-plan.json"
```

替换 `--as-of` 为实际检索日；省略时取当前日期。计划只供下一次检索使用，不是定时任务，也不表示已搜索。

DOI 去前缀并统一大小写；DOI/URL 对应且核心元数据一致时去重并保留 ID 别名。冲突保留在 conflicts，不覆盖原记录；相同标题只提示可能的版本关系。预印本与正式版保持独立 paper ID，通过相同 `work_id` 归组；每个关联必须提供 `relation_evidence` 官方 URL。工具保留各版本而不把预印本冒充期刊版。

主张审查指出缺失文献、元数据冲突和只有摘要却主张完整机制的问题。即便 `source_linked_human_verification_required` 也只是关联完整，需实际读文核对。增量计划保留同领域先例不限历史时间的规则。日期与 DOI 只做语法校验；题名、来源真实性、版本关系、撤稿更正状态仍需联网/人工核实。
