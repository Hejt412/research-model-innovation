# 预声明配对统计与决策

这是可选的结果分析功能。没有统计声明时仍输出原始配对、均值与标准差，CI 为 null，不自动判断收益。

## 在看结果前记录

在 E0/E1 的 evaluation 中填写相同 statistics，并为每个 metric 填写 direction、unit 和 min_improvement。min_improvement 是该单位下的最小绝对改善；fraction 中 0.01 表示一个百分点，不是相对提升 1%。

```json
{
  "statistics": {
    "method": "paired_bootstrap_basic",
    "independent_unit": "training_seed",
    "comparison_scope": "per_task_metric_unadjusted",
    "confidence_level": 0.95,
    "resamples": 10000,
    "min_pairs": 5,
    "random_seed": 42
  }
}
```

该片段放入 evaluation，不能替代 tasks/metrics/sampling。数值是格式示例，必须按研究问题在看结果前选择。min_pairs 至少 5 是工具的保守下限，不保证统计功效；resamples 支持 1000–50000，confidence_level 在 (0.5,1) 内。每个组最多 500 万次样本抽取，超过则报告预算限制，不静默改方法。

CSV 每行必须已经按单次独立训练运行聚合。episode、query、同一 checkpoint 的重复评估不作为训练 seed。只有种子不同也不能证明训练运行独立，需查日志和 checkpoint 来源。当前不支持层级 bootstrap 或跨任务总体推断。

## 算法与边界

先按 training seed 配对，计算 E1−E0；lower 指标取其相反数，使正值统一代表改善。对这些配对差值有放回地重采样、每次取同样数量，计算均值分布。用线性插值分位数 q，basic 区间为 `[2*原均值−q(1−α/2), 2*原均值−q(α/2)]`。固定 random_seed 使同一输入可重复，不调用项目代码，不需要 SciPy。

配对重采样和 basic 区间的定义可对照 [SciPy 官方 bootstrap 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)。本工具只实现上述受限方法，不声称等同于 SciPy 默认的 BCa 方法。

区间下界严格超过阈值：threshold_supported_exploratory；上界低于阈值：below_predeclared_threshold；否则 inconclusive。后两者不能写成“机制无效”或“等价”。各 task/metric 分开计算，不校正多重比较；不能挑选其中通过的任务作为整体有效证明。

观测缺失、配置未核实、数据/few-shot 冲突、源码覆盖不完整、对照与实验统计声明不同，都阻止统计判定。重复数不足、差值全部相同或预算超限时也不给 CI/收益结论。少量 seed 的 bootstrap 仍可能不稳定，即使区间通过阈值也不能证明机制因果性。

输出保留原始差值和方向调整后的区间，附声明与限制。manifest 能固定声明内容，不能证明它一定先于结果产生，preregistration_time_verified 永远不会凭文件内容自动变为 true。
