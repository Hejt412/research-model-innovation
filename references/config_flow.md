# 配置声明、构造输入与实例观测

三者分开记录：配置里的值不一定被工厂转发，构造参数也可能在 __init__ 内被强制覆盖。静态工具不能确认实际实例。

## 静态核对

先人工确认入口调用哪个工厂、工厂绑定哪个模型，再显式选择文件/函数/类。`trace_config.py` 不导入项目，仅解析 AST。

```bat
set "SKILL_DIR=%USERPROFILE%\.codex\skills\research-model-innovation"
python "%SKILL_DIR%\scripts\trace_config.py" --factory-file "D:\research\project\factory.py" --factory build_model --model-file "D:\research\project\models\model.py" --class-name Model --config "D:\research\records\factory-config.json" --out "D:\research\records\config-flow.json"
```

factory-config.json 是实际工厂使用的平面配置对象，不是 experiment_manifest 的规范化配置。默认配置参数名 cfg，可用 --config-param 更改；若模型通过别名调用，用 --constructor-name 指定源码中的确切调用名。只支持模块顶层工厂与类中显式定义的 __init__，多个候选调用拒绝猜测。

支持字面量、cfg 字段/索引/get、直接位置/关键字参数，以及由固定键列表构成的简单字典推导展开。记录参数来源、表达式、默认值、声明值、差异、源码位置及源文件/配置摘要。未转发但同名声明与构造默认值不同会标记 declared_input_mismatch。

动态 **kwargs、星号位置参数、无法解释的表达式、前置配置修改、条件工厂和装饰器保留 unknown。未匹配的配置键可能有别名，不能直接判为无用参数。工具不追踪构造器内部覆盖或证明导入绑定；即使 static_value 也只是候选构造输入。

## 用户自行运行的实例核验

交付 [实例核验脚本](../assets/verify_instance.py)。Codex 不在用户 ML 项目上执行它。脚本会导入用户指定的模块并调用工厂；用户须先确认导入、构造器和被读取的属性不会启动训练或其他不需要的操作。

kwargs JSON 应包含真实工厂所需的全部关键字参数。例如工厂签名 build_model(cfg, device) 对应 `{ "cfg": { "width": 64 }, "device": "cpu" }`；这里只演示格式，不是项目事实。配置引用对象或非 JSON 值时，先由用户准备一个经过审阅、仅负责构造的包装函数。

```bat
cd /d "D:\research\project"
set "PYTHONPATH=%CD%;%PYTHONPATH%"
python "%SKILL_DIR%\assets\verify_instance.py" --factory factory:build_model --kwargs "D:\research\records\probe-kwargs.json" --attribute width --attribute blocks.0.enabled --execute-reviewed-factory --out "D:\research\records\instance-observation.json"
```

脚本只请求实例构造和选定属性，不调用 forward/train/adapt、不加载 checkpoint。它不会阻止任意工厂自身的副作用，所以显式开关不替代代码审阅。输出类名、Python 版本、输入摘要、标量属性与无法解析的属性；复杂对象只记类型。用户回传后仍须与当时源码指纹关联，不能把它自动当成整个训练运行的复现。
