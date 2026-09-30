# 研究历史

所有观测保留来源；空值表示未知。历史按日期追加，不删除失败结果。

结果回流可用 [机制关联元数据](innovation_metadata_template.json) 的 `--innovation-metadata` 传入既有研究和 G/P/I/H 身份。schema 2 默认文献待查新，可用 `paper_ids=[]` 和 `literature_status=pending_search`（或 `unknown`）保留已知研究、I/G/H、四维机制和 E/manifest 关联；标记 `partial_declared`，不补造 P-ID。提供真实 P-ID 时使用 `references_declared` 和 `complete_declared`，两者均只是声明，仍待人工核验。未提供元数据时只归档用户观测，明确机制身份未关联、待人工补齐，不生成 ID。

历史使用独立 version=1 的稳定导入身份；工具 Git/安装标记、解析路径以及声明的卡片/运行文件定位变化不重复追加。原摘要保留所有路径和原文件摘要，实际证据、元数据非定位原字节、卡片正文、研究身份、统计、规则或 scripts 摘要变更追加修订，不覆盖此前条目。旧 marker 只能用可得的原摘要精确匹配；缺失原件不猜去重。指纹摘要仅用于精确内容比较，数学/概念等价须人工审查。

## {{H-ID}} — {{date}} — {{I-ID}}

- baseline/commit/config：{{baseline}}
- 研究 ID/来源创新卡路径与摘要：{{research_id, source_card_path, source_card_sha256}}
- 机制指纹（结构化 location/transformation/data_dependencies/objective）：{{fingerprint}}
- G-ID/P-ID/E-ID：{{evidence_ids}}
- 文献状态/声明关联完整性：{{references_declared_or_pending_search_or_unknown, complete_declared_or_partial_declared}}
- 对照/实验 ID 与各自 manifest SHA-256：{{control_and_experiment_identity}}
- 元数据原文件/规范内容 SHA-256：{{metadata_file_sha256, metadata_record_sha256_or_not_linked}}
- 稳定导入身份（独立 version/sha256）：{{history_identity}}
- 状态：{{proposed_or_implemented_or_evaluated_or_rejected}}
- 对照/唯一变化/固定条件：{{controlled_change}}
- 代码/配置/用户运行命令路径：{{artifacts}}
- 结果来源、日期、逐 seed 指标及统计：{{observed_or_not_run}}
- 结论、竞争解释、限制：{{interpretation}}
- 下次决策/重提条件：{{next_step}}
