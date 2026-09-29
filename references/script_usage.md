# 静态脚本使用

依赖：Python 3.12+ 标准库；不需要 PyTorch、GPU 或 API key。所有脚本只读源码，不 import 项目、执行模型、反序列化 checkpoint 或运行训练。只有 `--out` 指定的 JSON 被写入；将输出放项目外的临时目录或已排除的 `outputs`，避免后续扫描读回结果。

下例为 cmd.exe / Anaconda Prompt；将路径改为实际位置。`SKILL_DIR` 指向本 Skill 安装目录。

```bat
set "SKILL_DIR=%USERPROFILE%\.codex\skills\research-model-innovation"
python "%SKILL_DIR%\scripts\scan_project.py" "D:\research\project" --out "D:\research\analysis\project.json"
python "%SKILL_DIR%\scripts\analyze_models.py" "D:\research\project" --out "D:\research\analysis\models-before.json"
python "%SKILL_DIR%\scripts\extract_experiment_config.py" "D:\research\project" --out "D:\research\analysis\config-evidence.json"
```

修改后再次用 `analyze_models.py` 生成 `models-after.json`，然后：

```bat
python "%SKILL_DIR%\scripts\compare_models.py" "D:\research\analysis\models-before.json" "D:\research\analysis\models-after.json" --out "D:\research\analysis\comparison.json"
```

扫描脚本支持 `--max-bytes`（每文件默认 2 MB）及可重复的 `--exclude-dir`（目录名）。默认跳过版本控制、虚拟环境、构建、checkpoint、wandb、outputs 等目录及符号链接/Windows junction。只扫描 Python、常见文本配置和 Markdown；不解析 notebook、二进制或 `.gitignore`，需另行查看这些覆盖缺口。无效根目录以非零状态退出；单文件损坏以 `errors` 报告并继续，不能将部分报告当完整审计。

`scan_project.py`：路径级角色线索，必须读源文件核验。

`analyze_models.py`：识别常见 torch 导入别名、同文件 Module 继承以及含 forward 的候选类，输出 bases、self 赋值、方法范围、源码顺序调用、return 和 AST 指纹。跨文件继承、动态工厂、装饰器、嵌套函数/类、名称遮蔽可能误检/漏检；输出不是执行图。参数量始终 null，形状和 FLOPs 未测。

`compare_models.py`：比较相同 `file::class` 键和 AST 内容，保留输入的错误/跳过项；重命名视为新增/删除，重名歧义报错，不能自动推断模型演化或创新效果。

`extract_experiment_config.py`：提取配置相关赋值/调用及文本行；不求值、不合并配置、不解析运行时覆盖。缺失字段需人工读代码和运行记录补齐。
