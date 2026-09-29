# 配置、评估覆盖与数据身份规范

这是工具之间使用的规范化记录，不替代项目自己的配置系统。先读真实入口/CLI/日志，再整理字段。complete 仅表示本规范必填和已提供字段满足检查，不证明实际训练用了这些设置。

## 配置状态

- 缺失：missing。必填字段不能因未写出而默认为已知。
- `{"state": "unknown"}`：明确尚未核实，可保存草稿 manifest，不确认协议完整。
- null：只在 training.scheduler、training.augmentation、data.episode_plan_sha256 中表示明确停用/不适用。其他字段的旧式 null 作为未知保留，建议改为显式 unknown。
- 类型/值域错误：invalid，snapshot 拒绝生成。包括 bool/float/重复/负数 seed、负 lr、重复任务/指标名。

核心必填：model.baseline、data.dataset_id、protocol.split、protocol.target_label_access、training.seeds，以及 evaluation.sampling/tasks/metrics。身份与标签假设为非空字符串；seed 为非空、唯一的非负整数列表。sampling 为 episodic 或 fixed_split。

loss、optimizer、预算、预处理和环境等仍应按真实项目完整记录；未声明的专有参数不能自动发现。提供 lr 时须为正有限数，epochs/batch_size 须为正整数。

## 完整评估清单

看结果之前冻结 task × required metric × seed。任务名应区分 domain/shot/protocol，例如 A-to-B-1shot，不得把不同 shot 混为一个任务。

指标定义示例（不是默认实验事实）：

```json
{
  "sampling": "episodic",
  "tasks": ["A-to-B-1shot", "A-to-C-1shot"],
  "metrics": [
    {"name": "accuracy", "unit": "fraction", "direction": "higher", "role": "primary", "required": true},
    {"name": "macro_f1", "unit": "fraction", "direction": "higher", "role": "secondary", "required": true},
    {"name": "latency", "unit": "ms", "direction": "lower", "role": "secondary", "required": false}
  ]
}
```

主指标必须 required=true，辅助指标可选，不能事后为隐藏失败结果改成可选。输出分别包含任务覆盖、必需指标覆盖、任务/指标组合覆盖和 seed 配对完整性。整个任务或指标在两组均缺失也会发现；没有计划不能从 CSV 倒推完整。可选指标两组均缺失不影响必需覆盖，已经提交但缺配对仍需报告。

读取旧 manifest 时重新校验，旧配置不足降级为不完整。旧 audit 与新规则不同会拒绝导入，需保留旧记录并重新生成 audit；不需要重新训练，不重写原始结果。

## 数据与 episode 清单

[清单模板](../assets/data_plan_template.json) 是空骨架，不能作为证据。mode=episodic 必须有 episode；mode=fixed_split 必须是空 episode 列表。

samples 每项包含字符串 sample_id、record_id、device_id、split；few-shot 核对还要求被选样本的 class_id 是非空字符串。sample_id 唯一；record_id 标识原始连续记录，不得把同一记录的不同窗口伪装为独立记录。若协议允许同设备跨划分，不要随意开启设备隔离。

policy.split_disjoint_by 指定不可跨 split 重叠的身份，默认 sample_id/record_id；support_query_disjoint_by 指定 episode 内 support/query 不可重叠的身份；task_splits 指定各任务允许的 support/query split。

每个 episode 包含 task、整数 seed、episode_id、support/query 的有序 sample_id 列表。这里 seed 是结果配对使用的运行/训练 seed，与 training.seeds 对应；如果 episode 另有抽样 RNG seed，另存 sampling_seed，不能拿它替换运行 seed。保留 episode 和样本顺序；样本目录行顺序不影响摘要。snapshot 会与配置中的任务和 seed 交叉核对，附加 sampling_seed 也纳入摘要。

示意片段（样本必须存在于自己的 samples）：

```json
{
  "policy": {"split_disjoint_by": ["sample_id", "record_id"], "support_query_disjoint_by": ["sample_id", "record_id"], "task_splits": {"A-to-B-1shot": {"support": ["target_test"], "query": ["target_test"]}}},
  "episodes": [{"task": "A-to-B-1shot", "seed": 42, "episode_id": "0", "support": ["s1"], "query": ["q1", "q2"]}]
}
```

cmd.exe / Anaconda Prompt 命令：

```bat
python "%SKILL_DIR%\scripts\data_protocol.py" check "D:\research\records\plan-e0.json" --out "D:\research\records\data-check.json"
python "%SKILL_DIR%\scripts\data_protocol.py" compare "D:\research\records\plan-e0.json" "D:\research\records\plan-e1.json" --out "D:\research\records\data-comparison.json"
python "%SKILL_DIR%\scripts\experiment_manifest.py" snapshot "D:\research\project" --config "D:\research\records\effective-e0.json" --data-plan "D:\research\records\plan-e0.json" --experiment-id E0 --out "D:\research\records\e0.json"
```

检查样本/记录/可选设备跨 split 重叠、support/query 重叠、不存在的样本、重复 episode、错误 split 与清单顺序变化。清单不同或冲突时，相同 seed 不能确认公平比较。未提供清单可保存结果，但协议状态为 not_supplied，最终解释维持不完整。

工具只核对提供的身份与清单，无法发现错误重命名、未导出的 loader 状态、真实数据字节差异或错误标签。应由实际数据流程在用户环境导出；没有清单时提供导出设计，不在 Codex 训练获取。用户项目的样本 ID、设备身份、结果与源码不上传公共 Skill 仓库。

## Few-shot 计数声明

episodic 清单在顶层 few_shot 按任务声明以下正整数；不同 shot 必须用不同任务名。不要将 n_way/k_shot 直接放清单顶层，这会拒绝读取以防字段被忽略。

```json
{
  "few_shot": {
    "A-to-B-1shot": {"n_way": 4, "k_shot": 1, "query_per_class": 30, "episodes_per_seed": 20}
  }
}
```

每个 episode 的 support/query 都必须覆盖 n_way 个类别、类别集合相同；每类 support 恰好 k_shot，query 恰好 query_per_class。每个 task/运行 seed 的 episode 数与声明一致；缺少整个任务/seed 另由 snapshot 对照 evaluation 清单发现。可变 query 数、开放集或不同类别协议不能强行套此闭集检查，应单独定义协议并保留未核验状态。

旧 episodic 清单缺少 few_shot 时仍可读取，报告 incomplete_specification；审查为 few_shot_unverified，不能确认协议完整。fixed_split 不要求 few_shot。标签仅用于核验给定类别身份，不验证标签真实性，也不意味着允许模型使用 query 标签。

## 源码冻结覆盖

snapshot 支持 --required-file（可重复）、--exclude-dir 与 --max-bytes。应将审阅过的训练/评估入口、模型和关键辅助依赖列为 required-file；例如：

```bat
python "%SKILL_DIR%\scripts\experiment_manifest.py" snapshot "D:\research\project" --config "D:\research\records\effective-e0.json" --required-file train.py --required-file models/model.py --required-file models/stem.py --exclude-dir tests --experiment-id E0 --out "D:\research\records\e0.json"
```

source_coverage 与修改范围 status 分开：被跳过的大文件/链接、空源码集或 required-file 缺失使覆盖不完整；两份清单采用不同扫描设置也须重新核对。排除目录会列出，其不相关性仍由人工判断。complete_in_declared_scope 只表示当前声明的文本范围完整，不证明运行时依赖闭包；二进制数据、原生扩展、外部包不在其证明范围内。

不完整 snapshot 仍写出草稿报告，但退出 2；audit 和结果导入据覆盖状态阻止证据完整性确认。旧 manifest 没有 source_scope 时为 unverified_legacy_scope；如需新规则审查，从对应旧源码状态重新冻结，不能拿当前代码补成旧版本。

可选统计声明、指标方向和改善阈值见 [配对统计规范](statistical_decisions.md)。
