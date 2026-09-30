# 结构核验、观测归档与离线复核

本页用于实现/用户核验请求；分析方案只交付核验计划。Codex 不运行用户模型。核验入口 [verify_structure.py](../assets/verify_structure.py) 只依赖标准库，比较适配模块导出的观测，不认证观测真实性。

## 两个入口

用户执行：按已核实接口编写 `reviewed_structure_probe:collect(spec)`，在 eval/inference 环境构造 baseline/disabled/enabled，明确映射公共权重，复用实际输入并控制 RNG/状态。不调用训练入口、optimizer、backward；相同 seed 不自动保证相同公共权重。未知 API/接口时交付缺失项，不能承诺可运行。

```bat
set "SKILL_DIR=%USERPROFILE%\.codex\skills\research-model-innovation"
cd /d "D:\research\project"
set "PYTHONPATH=%CD%;%PYTHONPATH%"
python "%SKILL_DIR%\assets\verify_structure.py" --adapter reviewed_structure_probe:collect --spec "D:\research\records\probe.json" --source-file "models\model.py" --execute-reviewed-probe --out "D:\research\records\observation.json"
```

模块/路径需按项目替换。未显式启用时拒绝导入；spec 无效或输出指向输入/已列源码时，在导入前拒绝。入口在导入前、collect 返回后对核验脚本、普通文件适配模块及 --source-file 逐字节求摘要。变化、不可读或适配来源无法对应时为 changed_or_unconfirmed，不给总体通过。依赖闭包、执行中的暂时改动、加载的 bytecode 与磁盘文件是否同一份仍未认证；显式开关不是沙箱。

离线：读原始导出 JSON 或新报告内保存的 observation，不导入适配模块或项目，不需要执行开关。Codex 可复核用户提供的 JSON，不能为补观测启动模型。

```bat
python "%SKILL_DIR%\assets\verify_structure.py" --observation "D:\research\records\observation.json" --spec "D:\research\records\probe.json" --out "D:\research\records\recheck.json"
```

归档的 observation_sha256 不符直接拒绝；归档 spec 字节摘要或 context 与本次不符时可重新计算描述数据，但保持 failed_or_unconfirmed，不能将事后放宽容差包装成预声明通过。来源变化和上述限制在重复离线复核中保留。复核当前磁盘源码不会替代当时的快照。原始 JSON 无当时源码记录时为 not_assessed_offline，仅说明这些导出值通过声明检查。

## Spec 与输出

支持旧 spec schema_version=1，仍使用全局 setup；新 [模板](../assets/structure_probe_spec_template.json) 为2。报告 schema_version=2，旧 summary-only 报告没有原数值，不能凭摘要重建，须使用用户原始导出。实验记录 rules_version=2.2 不因此改变。

spec 必须含：
- probe_kwargs 对象；
- 非空 cases；各项唯一 id、input_shapes 与 expected_outputs，形状为正整数列表，[] 为标量；
- comparison.atol/rtol：看结果前指定的有限非负数。模板 unknown 须填实。

spec2 可选 context 关联 baseline/experiment 的 experiment_id 与 manifest_sha256，两者 ID 不同。摘要填实验工具给出的 manifest_sha256，不是随意的文件字节摘要；这些是关联声明，不表示此工具已经核验 manifest。后续完整结果复核仍使用原实验工具。

collect 返回全局 setup、cases；spec2 每个 case 还需 setup。五项 setup 均严格为 true：eval_mode、inference_mode、shared_input、baseline_state_matched、rng_reset。状态重置/输入关系的实际实现须审阅适配源码，布尔值不认证发生过什么。

```json
{
  "setup": {"eval_mode": true, "inference_mode": true, "shared_input": true, "baseline_state_matched": true, "rng_reset": true},
  "cases": [{
    "id": "example",
    "setup": {"eval_mode": true, "inference_mode": true, "shared_input": true, "baseline_state_matched": true, "rng_reset": true},
    "inputs": {"x": {"shape": [1, 2], "sha256": "实际输入摘要"}},
    "baseline": {"logits": {"shape": [1, 2], "values": [0, 0]}},
    "disabled": {"logits": {"shape": [1, 2], "values": [0, 0]}},
    "enabled": {"logits": {"shape": [1, 2], "values": [0, 0]}},
    "observables": {"branch": {"calls": 1}, "gate": {"shape": [2], "values": [0, 0]}}
  }]
}
```

例中零值/调用次数不是实测。values 为固定轴顺序展平的实际数值；输入 sha256 应覆盖实际字节、dtype 和 shape。入口检查完整 case/input/output 覆盖、维度、元素数、有限数与 disabled-baseline 容差。它使用有限导出数的精确有理数比较，避免中间减法/容差乘加溢出；相对项以 baseline 为参照。误差摘要含失败数量/首个下标与坐标、最大绝对误差及最差位置；相对误差只对非零 baseline 定义，零参照非零差值另计。超出浮点显示范围的误差用科学计数字符串保存，判定不依赖显示舍入。

报告嵌入原始 observation、规范化 JSON 摘要、spec 字节摘要、工具摘要、源码前后快照及 context。正常失败仍保存导出的实际数据和诊断，退出码2；spec/加载错误非零退出。非 JSON 或非有限数据不强造有效原观测，报告标记归档不可用并失败。未知类型/非有限 setup 等元数据也以不可用标记保存，不能写出非法 JSON。

## 按任务选用机制和状态检查

这些规则只适用于声明的案例；没有声明即 not_declared，不是已验证。仪器计数/中间值仍来自适配模块，须审阅其采集位置和条件。

spec2 的 mechanism_checks 各项需 id、intent、case、observable、kind：
- executed：min_calls >=1，对应 observables[name].calls。零初始化的真实执行分支可通过；不能仅靠输出相同判定分支未执行。
- range：shape、有限 min/max，检查中间张量值域。
- nonzero：shape、非负 atol，至少一个值超过该阈值。只在可预期非零的受控案例使用，不作为所有初始化的通用要求。

relations 各项需 id、intent、kind(close/different)、comparison、left/right。选择器含 case、variant(baseline/disabled/enabled)、output，以及可选的唯一有效扁平 indices；两侧元素数须相同。close 为所有元素在容差内；different 为至少一项超容差。不同不是机制有益或因果证据。

例：项目明确要求批次独立时，交换 batch 顺序后的 enabled.logits 可与原案例按映射比较：
```json
{
  "id": "batch-permutation",
  "intent": "任务要求逐样本独立，交换 batch 后按原顺序比较",
  "kind": "close",
  "comparison": {"atol": 0.00001, "rtol": 0.00001},
  "left": {"case": "original", "variant": "enabled", "output": "logits"},
  "right": {"case": "swapped", "variant": "enabled", "output": "logits", "indices": [2, 3, 0, 1]}
}
```

按实际任务/接口准备案例并预声明关系：
- 批次独立：交换顺序或加入无关样本，比较对应样本。transductive、跨样本 attention、few-shot episode 交互不默认满足。
- 缓存重置：经历不同历史后显式 reset 的输出与 fresh state 比较；连续状态若应携带历史，可另设受控 different，不能在所有输入上强求差异。
- 因果性：相同前缀、不同未来输入，比较前缀输出。非因果分类模型不强加因果要求。
- 全长/分块：仅当接口和状态语义声称两者等价时，适配模块导出全长与按原时间轴拼回的分块输出；不能随意对所有 Mamba 模型要求该性质。
- mask/padding：仅在项目语义规定不影响有效位置时，比较声明的有效输出索引。

所有已声明检查失败/缺失都会阻止总体通过。启用路径未声明关系时仍只检查形状/有限数；输出不同、调用次数或门控分布都不能证明性能或机制因果。报告保留 setup_verified/context_verified/dependency_closure_verified/performance_improvement_verified/mechanism_causality_verified=false。
