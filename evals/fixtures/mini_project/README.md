# 离线科研任务样本（合成验收数据）

用于验证 Skill 行为的微型项目，不是用户课题、真实训练结果或真实论文。

任务：跨设备时序分类，3-way 1-shot，输入 B×1×128。标签只允许使用 source train 和 target support，禁止读取 target query 标签做适配。当前运行入口配置选中 Baseline；Candidate 尚未被接受。测试脚本不得启动训练或导入项目。

用户计划加入“support 驱动的 prototype calibration”，希望判断是否值得研究。项目目录包含历史和一个待审配置，请结合源码判断。
