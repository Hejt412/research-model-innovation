# 合成项目输入

这是静态设计资料，没有真实训练日志、checkpoint 或论文。model_08.py 的 encoder/head 是已有 baseline；禁用 enabled 分支即 baseline。x 的形状 [B,16]，h 为 [B,32]，logits 为 [B,4]，target 为 [B] 的类别索引。任务是逐样本分类，推理只需要 x，没有缓存、跨样本状态或因果要求。

提案新增两层无偏置线性映射，rank=2，down/up 分别在初始化时赋上述代码中的值。所有模型参数可训练，make_optimizer 是当前配置的完整参数范围；training_loss 是实际唯一目标。没有另一个 loss、参数噪声、预训练残差权重或外部参数修改，优化器无已有状态。公共 encoder/head 的权重在 baseline 与提案中匹配。用户要求启用结构的初始 logits 与 baseline 一致，并保留能够学习的新分支。

本轮允许对提案作一个必要实施因素的最小修订；不得改 rank、加入 bias、替换 encoder/head、变更 loss、lr、优化器或数据协议来同时补偿。没有新结构收益实测，显存/延迟也未知。不要求在 Codex 内完成模型行为验证；如需要用户实测，应交付所需的独立运行计划及边界。
