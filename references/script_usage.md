# 静态脚本使用

依赖：Python 3.12+ 标准库；不需要 PyTorch、GPU 或 API key。本页四个源码工具只读源码，不 import 项目、执行模型、反序列化 checkpoint 或运行训练。只有 `--out` 指定的 JSON 被写入；将输出放项目外的临时目录或已排除的 `outputs`，避免后续扫描读回结果。新增实验、结果和文献工具见 [证据工具说明](evidence_tools.md)。

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

`analyze_models.py`：识别常见 torch 导入别名、本地 Module 继承以及含 forward 的候选类，输出 bases、self 赋值、方法范围、源码顺序调用、return 和 AST 指纹。继承展开范围见下文；动态工厂、装饰器、嵌套函数/类、名称遮蔽可能误检/漏检，输出不是执行图。参数量始终 null，形状和 FLOPs 未测。

`analyze_models.py` 的 schema v2 记录保守本地导入图、传递依赖和完整源码 AST 指纹。同文件辅助函数、包初始化、相对/循环导入可追踪；外部/动态导入未核验。默认扫描根为导入根，可重复传入 `--import-root src --import-root lib`。根必须在扫描目录内，模块重名标记 ambiguous_import，不猜测运行时 sys.path 顺序。过度近似可能包含未执行依赖。

可展开无歧义的本地单继承链，包含跨文件导入、继承 forward 和带来源位置的 effective_assignments/effective_methods。子类无构造函数时继承父类证据；有构造函数则仅在看到 super().__init__() 时纳入父类构造赋值。多继承、循环、未解析基类和未调用 super 的情况明确降级。条件 super、del、工厂和 monkey patch 仍需人工确认，不据静态展开证明运行时实例结构。

effective_* 表示合并继承后的静态源码线索，仍可能包含未启用的条件赋值；不能解释为实际实例组件。须追踪入口、工厂参数转发、构造默认值与分支守卫，配置提取工具不会自动完成这些核对。

`compare_models.py`：比较相同 `file::class` 键和 AST 内容，保留输入错误/跳过项；输出 class_source_changed、dependency_source_changed、dependencies_unverified 或 no_change_in_scanned_sources，不再输出含糊的 unchanged。读取旧 schema v1 时缺少依赖证据，不能推断行为等价。

显式指定两个不同模型，可在同一报告或两份报告中比较：

```bat
python "%SKILL_DIR%\scripts\compare_models.py" "D:\research\analysis\models-before.json" --left-model "models/FTFM.py::FTFM" --right-model "models/Unified_TF_Mamba.py::UnifiedTFMamba" --out "D:\research\analysis\peer-comparison.json"
```

输出类体赋值差异、双方基类/继承状态、展开后的组件证据和按表示/backbone/融合/分类器分类的关键词证据。assignments_removed 仍只针对类体；结构阅读应结合 effective_component_evidence，不能把子类未重复写 stem 当作删除。关键词不是语义结论。训练协议需另读入口及 manifest；未指定选择器时重命名仍视为新增/删除。

`extract_experiment_config.py`：提取配置相关赋值/调用及文本行；不求值、不合并配置、不解析运行时覆盖。缺失字段需人工读代码和运行记录补齐。
