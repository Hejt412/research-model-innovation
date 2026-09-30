# 记录格式、规则版本与工具身份

三种版本分别记录：

- schema_version：特定 kind 的数据格式。experiment_manifest、experiment_audit、observed_result_summary 现在是 2；run_ledger 与 config_flow_evidence 是 1。数据计划和文献账本仍沿用各自格式，不作无关迁移。
- rules_version：检查语义，目前为 2.2。后续改变判断规则时需要更新，而不只是保持同一个格式数字。
- producer：工具名、实际 scripts/*.py 的规范化内容摘要、可获取的 tool_commit，以及工作树是否有未提交改动。

创新关联元数据 `innovation_metadata` 和 Skill 行为索引/快照/复核记录另用独立 `schema_version=1`，分别由结果导入器与 [行为版本工具](behavior_versions.md) 验证，不参与 `record_versions.py` 的实验记录迁移。它们不改变实验检查规则 2.2；[创新关联用法](evidence_tools.md)将原字节与规范内容摘要分开，行为记录将实际报告摘要与所用规则/输入快照分开。结构 spec1/2、报告2也独立，见 [核验契约](structure_probe.md)。

脚本摘要将 CRLF 规范化为 LF，便于 Windows/Linux 对照。Git checkout 记录当前提交及 dirty 状态；压缩安装包可以携带 .tool-release.json（tool_commit、scripts_sha256），仅当摘要匹配时才采用提交标记。没有匹配元数据时 tool_commit=null，不能猜测最近发布版本。摘要和提交标记不是数字签名。

## 只读兼容检查

```bat
python "%SKILL_DIR%\scripts\record_versions.py" check "D:\research\records\old-e0.json"
```

不修改输入，不执行训练或重新分析。可用的状态包括 supported_current、legacy_recheck_required、unsupported_format、unsupported_rules、unverified_producer。未来/不支持的版本拒绝参与计算。旧 manifest 的原始内容摘要仍会检查，不能仅补字段就绕过原封存记录。

先检查格式是否可读，再检查显式规则版本是否已知。即使 schema_version 为旧版，未知规则仍是 unsupported_rules，不能降级为普通旧记录后继续使用或归档。已知规则 2.0、2.1 和未记录规则版本的旧资料保留 legacy_recheck_required。2.1 修正工厂语句顺序、参数绑定和版本检查优先级；2.2 进一步保守处理推导式作用域和未经核实的属性访问，旧结论须重新核验。文献账本继续使用独立的 schema_version=1，增加的别名审查和来源字段不自动改写已有账本；需重新合并生成新的审查结果。

check 只有 supported_current 时退出 0，其余状态退出 2。格式可读不代表源码冻结完整、数据无冲突或结果有效；仍须按实际研究协议审查。

## 保留原件的迁移

```bat
python "%SKILL_DIR%\scripts\record_versions.py" migrate "D:\research\records\old-e0.json" --out "D:\research\records\archived-e0.json"
```

迁移创建新的归档封套，保存原文件完整字节（含 BOM/换行）、原文件摘要、原记录版本信息和本次迁移工具身份。拒绝原地写入、覆盖现有输出或包装未知版本。原文件不变，旧 manifest SHA-256 和 CSV 引用不变。

这是无损归档迁移，**不是把旧研究结论自动升级为新规则通过**。manifest 读取器可以读取封套内原始 manifest，兼容状态仍按原记录判断。旧 audit 不能直接冒充当前审查；用原始对照/实验 manifest 重新运行 check，保存新的 audit。旧格式或生产者不明确时不会自动获得统计判定资格。

若要生成完整的当前版本 manifest，必须在确切的历史源码/配置状态下重新冻结并独立保存。不能用今天的源码替代历史代码，不能静默改写旧 CSV 的 manifest 字段。找不到对应材料时保留未知；归档迁移不需要训练。
