# 合成项目资料

model.py 是静态评审材料，首个可执行语句会拒绝执行。nn、tensor、zeros、sigmoid、cat、cross_entropy、AdamW 仅标记常规张量接口；材料没有运行依赖，也没有真实 checkpoint、训练日志、指标或论文。可以读文本或 ast.parse，不能 import 或执行。

任务是逐样本三分类。x_a、x_b 均为 [B,6]，来自同一个样本的两个模态；a、b 为 [B,4]，forward 输出 [B,3]，target 为 [B] 的类别索引。训练只调用 training_loss，make_optimizer 给出完整优化器范围。推理提供两路输入，不需要标签、support、缓存或跨样本状态。本资料没有 dropout、batch norm 或其他隐藏的融合/后处理；预测概率来自 predict_proba。模型参数默认可训练，freeze_head 为真时只冻结代码列出的 head 参数。

当前 baseline 的配置为 fusion_name="none"、head_kind="affine"、freeze_head=False。用户希望评审 cross_linear、cross_value、cross_gate 的预测行为及研究主张。允许的另两种 head 配置是 shared_affine 和 joint_mlp，也希望了解 freeze_head=True 对结论的边界影响；它们是独立配置条件，不要求与候选同时作为一个实验变化。各候选的公共 encoder/head 参数与相应 baseline 匹配，enabled=False 跳过 fusion。CrossValue 的 down/up 在两路共享，CrossGate 的 condition/alpha 在两路共享，CrossLinear 的两个映射独立。alpha 是可学习标量。初始化按源码给出，没有额外 loss、外部参数扰动或已训练状态。

用户当前关注两路共同条件对预测的影响，但尚没有证据显示 baseline 在此处构成任务瓶颈。没有已知收益或资源实测，本轮不查现实文献。诊断可以使用预先保留的验证样本：两组模态的组合合法性由项目数据规则确认，使用一致的任务/标签定义；标签可以随联合输入合法改变，不要求所有组合属于同一类别。并非任意跨类别或跨采集条件组合都有效。中间表示的替换若越出合法输入/表示范围，须说明限制。

如需实验，交付独立方案，由用户运行；本轮不执行模型、梯度或训练。结构比较保持 loss、优化器、学习率、数据划分和评价协议，任何 head/冻结条件变化单独对照。
