# 运行、权重与评估结果的来源

seed 是配对标签，不能单独证明发生了不同的训练运行。结果导入可关联完成运行的记录；没有记录仍保留描述统计，但不做 CI/阈值判定。

## 每次真实运行保留什么

由用户在自己的运行环境生成/收集以下材料，不在 Codex 启动训练补证：

- run_id：每个实际训练运行的唯一编号。同一次运行在不同任务/指标上评估应复用 run_id。
- experiment_id、整数 seed、当时 manifest_sha256。
- 实际用于评估的 checkpoint 文件；该运行专属的 training_log。
- 该运行的原始 results CSV，包含原有七列及 run_id；一个文件只包含一个运行，可含多个 task/metric。
- evaluation_log：结构化 JSON 评估回执，绑定上述身份及三个文件的 SHA-256。

回执格式（占位值必须换成真实导出值）：

```json
{
  "schema_version": 1,
  "kind": "evaluation_receipt",
  "run_id": "E0-sourceA-seed1",
  "experiment_id": "E0",
  "seed": 1,
  "manifest_sha256": "当时的 manifest SHA-256",
  "checkpoint_sha256": "评估所用权重文件的字节 SHA-256",
  "training_log_sha256": "该次训练日志的字节 SHA-256",
  "results_sha256": "该运行原始 CSV 的字节 SHA-256"
}
```

回执应由实际评估流程在用户环境记录，不能凭一个旧文件名猜测它属于哪个运行。现有日志不足时明确未知；事后手写的回执只构成声明，不是独立证据。

## 收集并核验

[运行清单模板](../assets/run_spec_template.json) 是空骨架。runs 每项包含 run_id、experiment_id、seed、manifest_sha256，以及 checkpoint_path、training_log_path、evaluation_log_path、results_path。相对路径以 spec 所在目录为基准。建议为一次对照使用只含相关 E0/E1 的清单。

```bat
set "SKILL_DIR=%USERPROFILE%\.codex\skills\research-model-innovation"
python "%SKILL_DIR%\scripts\run_records.py" capture "D:\research\records\run-spec.json" --out "D:\research\records\runs.json"
python "%SKILL_DIR%\scripts\run_records.py" check "D:\research\records\runs.json" --control "D:\research\records\e0.json" --experiment "D:\research\records\e1.json" --results "D:\research\records\combined.csv"
python "%SKILL_DIR%\scripts\import_results.py" "D:\research\records\combined.csv" --control "D:\research\records\e0.json" --experiment "D:\research\records\e1.json" --audit "D:\research\records\audit.json" --run-records "D:\research\records\runs.json" --out "D:\research\records\summary.json"
```

capture 按块读取文件字节计算摘要，不 import 项目、不反序列化权重、不执行日志，也不训练；大 checkpoint 的哈希需要相应磁盘读取时间。它核对回执和该运行原始 CSV，写入带摘要的 ledger，拒绝覆盖已有输出。ledger 保存本地绝对路径，移动文件后需要在保留旧记录的前提下重新收集。

check/import 会重新计算文件摘要、核对实际 manifest 与运行身份、确认合并 CSV 的每条观测存在于对应原始 CSV。缺少文件、哈希不符、错 seed/run_id、拼接了不同运行的指标等都会阻止统计使用。不同 run_id 共享相同 checkpoint 或训练日志摘要会提示重复来源；同一运行跨任务/指标的正常复用不会被视为多个训练重复。

## 如何解释结果

- not_supplied：没有提供运行记录，独立性未知。
- conflicts_or_unavailable：来源存在冲突或缺失，统计判定阻止。
- linked_artifacts_no_reuse_detected：给定文件已核对、未发现上述重复，可按已声明的独立重复假设做探索性统计。

最后一种状态仍令 independence_verified=false：字节摘要不是真实性认证，序列化不同的文件可能包含相同张量；日志不同也不证明训练独立。工具不读取张量来判断等价性。config/protocol 的 interpretation_status=review_required 同样不代表运行独立性已确认，必须同时看 run_provenance。

历史结果没有这些材料时保留原观测与未知状态，不要求重新训练来满足工具格式，不伪造 run_id 或回执。用户运行路径、日志、权重摘要和结果只保存在项目/本地工作目录，不发布到公共 Skill 仓库。
