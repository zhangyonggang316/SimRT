# 无界面共享层验证

2026-10-07，在原目录分类之后，将现有协议与服务包独立到 `shared/python/`；保留包名和行为。

| 检查 | 结果 |
| --- | --- |
| APP Qt/原生核心 | 172 项通过 |
| 无界面共享服务 | 191 项通过，测试入口只加入共享源码路径 |
| 协议与边界检查 | 32 项通过 |
| APP PowerShell 入口语法 | 通过 |
| APP requirements 离线解析 | 通过，共享依赖均已安装；未进行安装 |
| 当前 Demo 与既有便携 Demo 导入 | 均识别 6 个观测量、12 个标定量，SSH/XCP 未连接 |

完整 APP/服务结果和源码哈希见 `test_report.json`。
协议测试包括 `tests/protocol/test_shared_boundary.py`：独立进程仅提供 `shared/python`，
禁止 Qt、Matplotlib、APP 及工具链模块导入，遍历导入所有协议与服务模块；SSH 服务可独立导入。
Demo 复测记录位于 `../layout_results/layout_import.json`。

直接依赖为 pyxcp 0.22.32、paramiko 4.0.0、traitlets 5.11.2，见 `shared/requirements.txt`。
APP 依赖文件引用它，打包源码搜索路径和预设检查脚本也使用共享路径。
正式 EXE、DLL 及先前便携包二进制未变，本轮没有重打包或再次启动 EXE。
没有调用 MATLAB 或连接实时机，也没有删除此前保留的便携验证包。

```powershell
& ./.venv/Scripts/python.exe -u -X utf8 app/qt_xcp_host/validate_tests.py --output tests/app/shared_results
$env:PYTHONPATH = 'shared/python'
& ./.venv/Scripts/python.exe -m unittest discover -s tests/protocol -v
& ./.venv/Scripts/python.exe -u -X utf8 tests/app/validate_layout.py
```
