# 结构方案、资源约束与用户核验

在候选具备问题和迁移证据后完成本表。源码阅读能确认的设计条件与用户运行才能确认的行为分别记录，不把完整表格当成通过实验。

| 核对项 | 应记录的内容 | 无法满足时 |
|---|---|---|
| 修改位置与原/新计算 | 文件/类/函数、替换的运算、信息路径或状态关系、与已有模块的实质差异 | 保留假设，不靠新名字宣称创新 |
| 输入输出与轴 | 每个入口/分支的形状、batch/channel/token 等轴语义、变长与边界输入 | 未核实形状标记待核验 |
| 连接与残差 | 投影、拼接、广播、残差维度和归一化；必要接口变化是否引入第二因素 | 维度冲突阻止直接实现 |
| 信息可用性 | 条件来自输入/support/状态还是标签，训练与推理分别能获得什么 | 所需信息不可得时拒绝当前方案 |
| 状态与执行约束 | 因果/非因果设定、mask、padding、跨样本状态清理、共享参数、dtype/device | 不符合任务假设时缩小或改写方案 |
| 底层接口 | 已阅读的依赖版本与接口，是否需要改 kernel、缓存或自定义算子 | 未提供的 API 不写成可直接调用 |
| 禁用与初始化 | 关闭机制如何恢复 baseline、公共参数如何匹配、初始化及随机状态控制 | 未核验的等价性只作为设计目标 |
| 成本与项目预算 | 参数增量、峰值显存、推理延迟、实现复杂度，以及来源和测量条件 | 超过明确预算时降级；成本未知不能当作满足预算 |

每项标记 `design_checked`（由列明的源码/公式核对）、`pending_user_probe` 或 `blocked`，附证据。设计可行性、实际运行核验和性能结果是不同结论。

## 项目预算

可在 [项目档案](../assets/research_profile_template.yaml) 的 resource_budget 填写上限。null 表示用户尚未指定；不自动赋予通用阈值。参数增量 fraction=(新参数量−baseline 参数量)/baseline 参数量，须说明是否包含 frozen/shared 参数及 baseline 配置。显存单位 MiB，延迟单位 ms，并列出硬件、输入形状、batch、dtype、软件版本与测量方式。实现复杂度使用项目约定，例如允许修改的层级/依赖，不制造精确分数。

分别记录用户上限、源码/公式估计、用户实测和当前未知项。估计超过明确上限可淘汰或要求缩小方案；估计低于上限只能暂时保留，不能报告实测合格。没有预算时仍报告成本未知，不阻止所有探索。资源补偿导致 lr、训练预算等同时变化时重新设计对照。

## 机制观测与消融

每个深入候选把一个具体结构假设连到可观测量、位置、采集条件、预期趋势、否定条件和一个相关对照。例：路由假设可观察逐条件权重及误差分组，用固定/均匀路由检验输入依赖是否必要；跨分支交互可用独立分支或中性交互作对照。这些只是可选形式，必须适合实际机制，不能据权重分布直接证明因果。

先选择最能区分竞争解释的最小观测；说明与最终指标的关系。观察到预测行为但性能无改善，或容量匹配的普通模块同样改善时缩小主张。中性版本须说明是否改变参数/计算或数据假设；与 E0/E1 分别定义唯一因素。不为记录中间量同时更改 loss 或训练策略，诊断和实验均由用户运行。

## 用户运行的结构核验

交付 [核验入口](../assets/verify_structure.py) 与按真实项目编写的适配模块、spec 和 cmd 命令。适配模块 `collect(spec)` 在用户环境构造 baseline、机制禁用和启用三种路径，使用共享的实际输入、匹配的 baseline 公共权重和受控随机状态；在已审阅的 eval/inference 环境执行 forward，不执行优化器、反向传播或训练入口。Codex 不在用户项目运行它。无法核实真实接口时交付缺失清单，不能声称适配模块可运行。

适配模块按本页契约导出输入摘要和实际输出数值；核验入口只验证导出的数据。适配模块/导入/forward 仍可能有副作用，显式开关不是沙箱。baseline 权重须从同一份状态明确映射公共参数，不依赖相同 seed 自动匹配；不使用待比较模型各自独立随机初始化来证明等价。

spec 是 schema_version=1 的 JSON，包含非空 cases、probe_kwargs 和 comparison。每个 case 有唯一 id、input_shapes（输入名→正整数形状）和 expected_outputs（输出名→正整数形状，可用 [] 表示标量）。comparison 包含预先指定的非负有限 atol/rtol。可使用 [spec 模板](../assets/structure_probe_spec_template.json)；unknown 项须先补齐。根据实际模型加入不同 batch、长度、mask/状态重置等有意义的案例，不只检查一个随机输入。

适配模块返回：

```json
{
  "setup": {
    "eval_mode": true,
    "inference_mode": true,
    "shared_input": true,
    "baseline_state_matched": true,
    "rng_reset": true
  },
  "cases": [{
    "id": "case-id",
    "inputs": {"input-name": {"shape": [2, 4], "sha256": "真实输入内容摘要"}},
    "baseline": {"output-name": {"shape": [2, 3], "values": [0, 0, 0, 0, 0, 0]}},
    "disabled": {"output-name": {"shape": [2, 3], "values": [0, 0, 0, 0, 0, 0]}},
    "enabled": {"output-name": {"shape": [2, 3], "values": [0, 0, 0, 0, 0, 0]}}
  }]
}
```

这里只演示结构，零值不是项目观测。values 是按固定轴顺序展平的实际张量值，sha256 按实际输入字节与 dtype/shape 一起生成。三条路径真正复用输入由适配实现审阅；摘要和 setup 均是声明，不是真实性认证。入口检查覆盖、形状、元素数、有限值，并逐元素验证 `abs(disabled−baseline) <= atol + rtol*abs(baseline)`。缺失、重复、多余案例/输出或不合格数据不通过；setup 不全为 true 时不会给总体通过。

输出仅支持这些输入/条件下的数值一致性，不证明全部输入、训练态、缓存或性能等价，也不证明启用后更好。启用路径只检查形状与有限输出，不要求等于 baseline。保存 spec/适配源码和列明依赖摘要；依赖闭包、setup 和训练未发生均不能由导出数据自动认证。

```bat
set "SKILL_DIR=%USERPROFILE%\.codex\skills\research-model-innovation"
cd /d "D:\research\project"
set "PYTHONPATH=%CD%;%PYTHONPATH%"
python "%SKILL_DIR%\assets\verify_structure.py" --adapter reviewed_structure_probe:collect --spec "D:\research\records\structure-probe.json" --source-file "models\model.py" --execute-reviewed-probe --out "D:\research\records\structure-observation.json"
```

模块名、路径和参数须按实际项目替换。没有显式开关时入口拒绝导入适配模块；已完成的失败核验保存诊断并返回非零退出码，spec 无效或适配模块报错时报告错误并退出。
