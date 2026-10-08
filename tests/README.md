# 测试与验证

| 目录 | 内容 |
| --- | --- |
| `app/ui`、`app/services` | Qt 界面、C++ 数据核心及上位机服务测试 |
| `protocol` | 共享 XCP 协议后端测试 |
| `toolchain` | MATLAB 目标、Python 本地构建与实时源码包测试 |
| `drivers` | Serial、Network、EtherCAT、CAN 等离线夹具和驱动测试；DIO 仅保留参考 |
| `linux` | 实时机控制台测试 |
| `tools/scripts`、`tools/unit` | SSH 联调与验收脚本，以及这些脚本的本地单元测试 |
| `validation` | 历史验收日志、JSON、截图、模型和构建证据 |
| `maintenance` | 工程快照、历史归档校验和可再生输出清理工具 |
| `layout` | 本次功能分类迁移清单、路径适配及验证结果 |

在工程根目录运行：

```powershell
.\.venv\Scripts\python.exe app\qt_xcp_host\validate_tests.py --output tests\app\new_results
.\.venv\Scripts\python.exe -m unittest discover -s tests\toolchain
.\.venv\Scripts\python.exe -m unittest discover -s tests\tools\unit
.\.venv\Scripts\python.exe -m unittest discover -s tests\linux
```

MATLAB 注册后运行 `runLocalTests`。`tools/scripts` 中的联调脚本可能连接实时机或启停测试模型，按对应说明选择参数；本地单元测试不需要实时机在线。

历史报告中的绝对路径是当时事实，原始 JSON、日志和部署 ZIP 没有因目录搬迁而批量改写。查找旧文件时使用 [路径映射](layout/move_map.json)；需要新构建时从新位置重新生成，避免使用旧 Makefile 中的绝对路径。学习说明与当前文档链接已同步到新位置。
