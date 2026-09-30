# 研究历史

所有观测保留来源；空值表示未知。历史按日期追加，不删除失败结果。

结果回流可用 [机制关联元数据](innovation_metadata_template.json) 的 `--innovation-metadata` 传入既有研究和 G/P/I/H 身份。未提供时只归档用户观测，明确机制身份未关联、待人工补齐，不生成 ID。元数据变更追加修订，不覆盖此前条目；指纹摘要仅用于精确内容比较，数学/概念等价须人工审查。

## {{H-ID}} — {{date}} — {{I-ID}}

- baseline/commit/config：{{baseline}}
- 研究 ID/来源创新卡路径与摘要：{{research_id, source_card_path, source_card_sha256}}
- 机制指纹（结构化 location/transformation/data_dependencies/objective）：{{fingerprint}}
- G-ID/P-ID/E-ID：{{evidence_ids}}
- 对照/实验 ID 与各自 manifest SHA-256：{{control_and_experiment_identity}}
- 元数据原文件/规范内容 SHA-256：{{metadata_file_sha256, metadata_record_sha256_or_not_linked}}
- 状态：{{proposed_or_implemented_or_evaluated_or_rejected}}
- 对照/唯一变化/固定条件：{{controlled_change}}
- 代码/配置/用户运行命令路径：{{artifacts}}
- 结果来源、日期、逐 seed 指标及统计：{{observed_or_not_run}}
- 结论、竞争解释、限制：{{interpretation}}
- 下次决策/重提条件：{{next_step}}
