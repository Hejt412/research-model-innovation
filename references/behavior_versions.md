# 行为验收版本、输入与定向复跑

适用于维护者管理 Skill 行为案例。读 [行为验收](behavioral_acceptance.md) 决定实际审查范围；本工具只检查记录和输入对应，不判论文事实、新颖性、性能或机制因果。`passed` 是维护者对一份实际报告的行为复核，不能认证科研结论。此契约独立使用 `schema_version=1`，不沿用或改动实验工具的 `rules_version`。

## 公共索引与冻结范围

从 [索引模板](../assets/behavior_case_index_template.json) 复制新的公共索引。模板只列案例，不含验收记录，所有案例默认未验收。索引记录 `case_id`、`rule_tags`、一个 `request_path`、明确的 `fixture_paths` 和 `source_paths`；`shared_source_paths` 对所有案例适用。路径只允许相对根目录的 POSIX 文件路径，不允许目录递归、绝对路径、`..`、反斜杠、盘符或大小写碰撞；解析后的文件也须在根目录内。跨平台保守拒绝任一路径组件末尾的点/空格、Windows 保留设备名和禁用字符，避免 Windows 将不同写法解析为同一文件；在其他平台也应用这些限制。

`source_paths` 必须覆盖该次实际交给评估者的 Skill 规范和工具源码，包括实际使用的辅助脚本及其本地依赖。模板示范规范范围；维护者应按实际发给评估者的材料补齐，不能为了维持旧通过而缩减列表。请求和 fixture 放在输入组，Skill/工具与复核标准放在来源组。独立评估者只拿请求、Skill 和相关原始 fixture；维护者 rubric 可纳入来源冻结，但不能预先交给执行者。新增案例或改变规则覆盖关系时明确更新索引。

输入组与来源组的路径按大小写折叠检查交集。`case-snapshot` 还在实际根目录解析路径并用文件身份检查，拒绝两组之间的内部符号链接或硬链接别名；普通不同文件即使内容完全相同也允许。离线 snapshot/record 格式与摘要验证没有文件系统身份信息，不能认证历史物理文件互相独立；登记只是保存已有快照与人工复核。`check` 在当前根目录重新执行文件身份检查，别名出现后不能成为当前通过；原历史身份仍依赖维护者保留的输入与实际审查。

冻结只读文件字节，不导入项目、不运行模型或 Git。每个文件把 CRLF 和 CR 转为 LF，记录规范化字节数与 SHA-256；按路径排序后将整个文件清单作规范 JSON SHA-256，集合摘要同时绑定路径与成员。案例还冻结两组摘要和案例声明摘要；索引中其他案例的变化不使本案例自动漂移。报告摘要使用原始字节，不规范化换行。摘要不是数字签名，也不能证明材料范围完整或报告真实独立。

## 冻结、复核与追加登记

以下命令兼容 cmd.exe / Anaconda Prompt，在仓库根目录运行。用用户任务目录保存快照与报告，公共历史只保存审查元数据和摘要，不上传报告原件、私有源码或私有路径。示例路径须替换为实际本地路径。

先在评估开始前冻结索引中某个案例：

```bat
python -X utf8 scripts\behavior_records.py case-snapshot --index evals\behavior_case_index.json --root . --case 01 --out "D:\local-review\01-inputs.json"
```

也可用通用函数对显式文件列表生成独立快照；这种通用快照不能直接当作案例验收登记：

```bat
python -X utf8 scripts\behavior_records.py snapshot --root . --files SKILL.md references/structural_design.md --out "D:\local-review\selected-source.json"
```

将实际冻结的原始材料交给独立评估者，报告写到独立本地目录。维护者读报告原件，复核行为、引用及未覆盖场景，并确认报告对应上述来源和输入，再登记：

```bat
python -X utf8 scripts\behavior_records.py register --snapshot "D:\local-review\01-inputs.json" --report "D:\local-review\01-report.md" --record-id review-01-20260930 --reviewer maintainer --verdict passed --source-match confirmed --reviewed-at 2026-09-30T08:00:00Z --out evals\behavior_history\review-01-20260930.json
```

`verdict` 可选 `passed`、`failed`、`needs_review`；`source-match` 可选 `confirmed`、`unknown`、`mismatch`。确认来源对应是维护者审查事实，工具不会从自然语言或相同文件名推断。禁止用当前快照替换报告产生时的历史输入；原始输入缺失时保留未知。输出保存实际报告的 SHA-256/字节数、冻结案例、复核身份/日期/范围，**不保存报告路径**。工具不认证评估者独立性。

可显式添加 `--tested-commit` 加完整历史提交 hash，或 `--base-commit` 加完整 hash 和 `--dirty true` / `--dirty false`。两种提交形式互斥；来源是当前未提交工作树时使用后一种。两者均省略则记 `snapshot_only`，工具不猜提交。提交身份仅作历史说明，不能替代内容摘要，也不要求今天的 Git HEAD 与历史提交相同。

每次登记创建一个新的历史 JSON，拒绝覆盖已有文件，包括相同路径的重复登记。复跑、修正复核或报告都使用新 `record_id`、日期和输出文件；旧记录保留原字节。若旧登记缺真实报告或输入摘要，不把旧“通过”文本补写成已验证记录。工具拒绝未来格式、摘要自洽失败、缺字段及额外私有路径字段。

## 检查当前输入与特定历史验收

```bat
python -X utf8 scripts\behavior_records.py check --index evals\behavior_case_index.json --root . --record evals\behavior_history\review-01-20260930.json --report "D:\local-review\01-report.md"
```

只有以下条件同时成立时该记录的 `current_pass=true`：记录格式/内部摘要自洽、案例声明与两组当前文件摘要一致、维护者 verdict 为 passed、来源对应为 confirmed、实际本地报告原件摘要/字节数匹配。通过退出 0，其他状态或无效参数退出 2；无效格式直接拒绝读取。未提供 `--report` 或报告缺失时可以得到 `inputs_match`，但不能成为当前通过。报告路径不进入结果 JSON。

结果列出 `case_definition_drift`、`request_or_fixture_drift`、`source_drift`、`input_unavailable`、`review_not_passed`、`report_source_not_confirmed`、`report_unavailable` 或 `report_bytes_drift`。这检查的是显式指定的一次历史复核，不自动代表全套案例、最新汇总状态或现实研究质量。公共矩阵应区分历史通过、当前输入对应、当地报告原件核对结果与未验收范围。

## 按变更规则定向复跑

维护者依据本次实际改动给出索引已登记的规则标签；这一步不是从 Git diff 自动推断规则，也不调用模型或 CI 评估器：

```bat
python -X utf8 scripts\behavior_records.py rerun --index evals\behavior_case_index.json --changed-rule initialization_learnability resource_budget
```

结果给出命中的 case、rule_hits、请求/fixture 路径和 reasons。未知标签拒绝，防止拼写错误静默漏测。可以追加 `--root . --records` 和一组显式历史文件，额外纳入这些记录在当前输入上的漂移：

```bat
python -X utf8 scripts\behavior_records.py rerun --index evals\behavior_case_index.json --changed-rule resource_budget --root . --records evals\behavior_history\review-01-20260930.json evals\behavior_history\review-07-20260930.json
```

同一案例按给定历史中最新复核时间检查漂移；重复 record_id 或无法唯一确定最新复核的同刻记录拒绝。未登记的其他案例不会自动扩大定向列表，失败但输入未漂移的案例也不会仅凭该状态加入；选择规则覆盖仍由维护者负责。列表只准备复跑材料，`evaluation_dispatched=false`，没有通过宣告。实际执行和报告复核后追加新登记。

Python 接口可组合：`snapshot(root, files)`、`case_snapshot(index, case_id, root)`、`register(frozen_snapshot, report_path, record_id, reviewer, verdict, source_match, ...)`、`write_new(record, destination)`、`check_current(index, root, record, report_path=None)`、`rerun_plan(index, changed_rule_tags, root=None, records=())`。它们只依赖标准库；合成测试位于 `tests/test_behavior_records.py`，不导入 fixture 项目或训练。
