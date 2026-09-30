# 初始化学习路径、结构取舍与版本对应复核

日期：2026-09-30。两个独立执行者分别执行新08/09及定向重跑01/05/07，只拿新版 Skill、原始请求与对应 fixture，没有 rubric、预期答案或其他报告。没有执行静态工具、项目、forward、backward 或训练。维护者全文阅读五份实际报告后登记；公共记录保存报告原字节摘要，不上传报告原件或本地路径。

来源为基于提交 `1530fa60d71f2127a49c763085c2da22a1bcc3eb` 的未提交工作树，明确 `dirty=true`，同时保存每份请求/fixture与所用规范的规范化文件摘要及集合摘要。没有把尚未创建的发布提交写成已测试提交。

首轮case快照遗漏执行者读取的 `references/protocol_contract.md`。该文件未改，先前发布提交及本地旧验证记录已经封存其原字节SHA-256 `6394906ef8a8605a35f27ed882c2b2a017e52316cf50760365f612ae983d5fb0`。维护者核对 Git 原文件、本地旧摘要与当前内容一致，将这一先前冻结来源与首轮快照组合为完整来源；其余全部初始输入/来源摘要一致。原快照、完整快照与补充依据均保留在本地，没有用修改后的文件替换历史证据。

| 案例与规则 | 实际报告中的决策、数学及限制 | 对应记录 |
|---|---|---|
| [01结构优先](structure_priority/request_01.md)：结构优先、学习路径、单因素 | 条件性选择S，L为独立备选；共享tanh门控，1348基线及1056/78.34%新参数化估算，零初始化局部导数与优化器未知分开；未查新、未运行。 | [本轮复核通过](behavior_history/review-01-20260930-choice.json) |
| [05自主结构](structure_design/request_05.md)：结构生成、学习路径、单因素 | 自主提出共享跨路通道残差；源码加性关系不等于已证实瓶颈，初始化潜在信号与真实核验分开；无预算时不强设上限。 | [本轮复核通过](behavior_history/review-05-20260930-choice.json) |
| [07参数化预算](structure_design/request_07.md)：预算、学习路径、单因素 | 拒绝完整共享g的78.34%；双bias低秩162/12.02%另估，α未知保留；区分可学习的输出bias与被阻断的交叉条件路径，单独用户诊断。 | [本轮复核通过](behavior_history/review-07-20260930-choice.json) |
| [08初始化](structure_choice/request_08.md)：学习路径、单因素 | 两因子双零使梯度恒零；仅改down为非零初始化，up保持零，保留初始baseline等价及阶段学习条件；独立用户脚本没有optimizer.step，未执行。 | [本轮复核通过](behavior_history/review-08-20260930-choice.json) |
| [09多结构取舍](structure_choice/request_09.md)：结构取舍、预算、学习路径 | Gate/Value各128参数约9.50%；Dense约78.34%淘汰；Gate条件性首试、Value保留，说明后者非线性值路径在线性head下仍加性，目标与最小区分诊断明确。 | [本轮复核通过](behavior_history/review-09-20260930-choice.json) |
| [02不可行](structure_priority/request_02.md)、[03用户方向](structure_priority/request_03.md)、[04硬预算](structure_priority/request_04.md) | 历史通过，输入内容对应5a95c63；本轮未重跑，未迁移为当前快照通过。 | [历史复核](structure-priority-acceptance-2026-09-30.md) |
| [06概念先例](structure_design/request_06.md) | 历史通过，输入内容对应1530fa6；本轮未重跑，未迁移为当前快照通过。 | [历史复核](structure-design-acceptance-2026-09-30.md) |

[公共案例与规则索引](behavior_case_index.json)用于维护者定向选择。本次变更标签为 `initialization_learnability`、`structure_choice`，命中01/05/07/08/09；其他旧结论保留历史身份。工具不会由“通过”文字认证科研结论，未登记案例也不自动扩大定向运行范围。

本地原始报告、完整来源与公共登记已逐案核对，可得到 `current_pass=true`；发布时再次核对最终文件内容。只有本地实际报告原件摘要匹配才能得此状态，公共仓库单凭来源摘要不能宣称当前通过。复核和用户研究有效性分别记录。

范围限制：这些合成静态案例不证明真实autograd信号、优化收敛、联网查新质量、复杂模型或性能。前向样本核验、单元测试、来源匹配和科研行为复核不是同一个结论。
