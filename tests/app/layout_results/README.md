# APP 目录分类验证

2026-10-07，验证源码和正式 APP 移动后的导入、模型加载、便携打包与启动；没有连接实时机。

| 检查 | 结果 |
| --- | --- |
| Qt 与原生核心回归 | 172 项通过 |
| 共享服务回归 | 191 项通过 |
| XCP 协议回归 | 31 项通过 |
| APP PowerShell 脚本解析 | 通过 |
| 正式 Demo 与便携 Demo 的 ZIP/A2L 导入 | 均识别 6 个观测量、12 个标定量，SSH/XCP 未连接 |
| 已迁移 EXE 与便携包 EXE 启动 | 均创建 SimRT 窗口，无新增启动错误日志 |

完整测试记录见 `test_report.json`、`qt_tests.log`、`baseline_tests.log`。
路径及模型导入记录见 `layout_import.json`，正式 EXE 校验见 `executable_startup.json`。
EXE SHA256 为 `5c8c20fb296672b882d39bb6c1b2d6d283bfdac93b3013e1104cc62d42df2e02`，本次没有重新编译 APP 或 DLL。

回归过程中修正了测试夹具在 Windows 短文件名临时目录下的路径比较；TCP 回环首次连接超时、临时 ZIP 占用在早期运行中出现过，未修改产品通信逻辑，随后单独回环及完整回归均通过。这些测试不证明实时机时序或硬件性能。

在工程根目录复现：

```powershell
& ./.venv/Scripts/python.exe -u -X utf8 app/qt_xcp_host/validate_tests.py --output tests/app/layout_results
$env:PYTHONPATH = 'app/qt_xcp_host;app/python'
& ./.venv/Scripts/python.exe -m unittest discover -s tests/protocol -v
powershell -NoProfile -ExecutionPolicy Bypass -File app/qt_xcp_host/package_demo.ps1 -ApplicationDirectory app/distribution -OutputDirectory tests/app/layout_results/portable_package
& ./.venv/Scripts/python.exe -u -X utf8 tests/app/validate_layout.py
powershell -NoProfile -ExecutionPolicy Bypass -File tests/app/validate_executable.ps1
```

便携包仅是打包验证的生成物，清单位于 `portable_package.json`。
自动审批策略拒绝了删除本次生成包的清理命令，因此 `portable_package/` 暂时保留，正式 APP 仍为 `app/distribution/`。
重新执行打包前，须使用不存在的输出目录。模板便携包保持 `app/`、`models/`、`demo.json`、`validation/` 自包含布局，与完整工程的五类目录分开。
