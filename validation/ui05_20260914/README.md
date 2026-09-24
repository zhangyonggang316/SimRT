# UI-05 验证记录

需求来源：工程根目录 `需求说明.md` 的 UI-05。本次仅调整 Qt APP，不修改模型、C++ 核心或 1 ms 实时调度。

## 变更与结果

- “部署与运行日志”统一到“实时机 / 诊断日志”，只保留一份日志流；读取、复制全部、清空显示、保存均集中在诊断页和其右键菜单。
- 移除启动参数输入。直接启动、模型列表启动和设置开机自启均不传附加参数。
- 移除模型部署页的刷新状态、读取日志、取消任务按钮及模型右键的重复日志入口。
- 自动状态查询更新 ELF 运行状态；关闭 APP 仍保留内部取消任务、恢复标定及断开连接保护，不自动停止远程 ELF。
- Qt 69 项与原业务 234 项测试全部通过，无失败、错误或跳过。UI-05 专项 10 项覆盖控件移除、单次日志转发、选中模型日志、异常重试、控件启用条件、默认参数、复制/清空/保存和自动进程状态更新。
- 四个视图各在 1320×820 和 1000×660 逻辑尺寸验证，共 8 张截图；未发现按钮裁切或超出父容器，曲线画布非空。
- 交付 EXE 已从工程外工作目录启动，并用 computer-use 检查真实部署页和诊断页。默认 A2L 正常加载，未自动连接目标机；无 SSH 时读取运行日志禁用，复制、清空显示、保存按钮可见。
- 交付 APP 的 1386 个文件与构建输出逐文件 SHA256 一致；332 个模型文件与原交付清单一致。旧 EXE、构建报告和基础库压缩包保留在完整工程的 `docs/history/qt_pre_ui05_20260914.zip`，恢复对应路径见 `delivery_report.json`，恢复前必须关闭 APP。

## 证据与复现

`test_report.json` 记录两套测试结果及对应源码 SHA256，详细输出见测试日志。
`visual_report.json` 记录窗口尺寸、布局检查及画布像素检查；PNG 为 Windows Qt 测试夹具截图，不是目标机实时数据。
冻结 EXE 和交付文件核验另见 `delivery_report.json`。

在完整工程根目录运行：

```powershell
& ./.venv/Scripts/python.exe ./qt_xcp_host/validate_tests.py --output ./validation/ui05_rerun
& ./.venv/Scripts/python.exe ./qt_xcp_host/validate_visual.py --output ./validation/ui05_rerun
& ./qt_xcp_host/build.ps1 -SkipNativeBuild
```

本次没有连接 Ubuntu、启停远程模型或重新执行 MATLAB SDI 导入。历史模型真机报告不能替代本版 APP 的真机联调。
此前 Qt 初版验收保留在完整工程的 `validation/qt_ui_20260914/`，升级后交付包的历史证据位于 `validation/qt_ui_initial_20260914/`；交付包 `validation/qt_ui/` 对应本次 UI-05。
