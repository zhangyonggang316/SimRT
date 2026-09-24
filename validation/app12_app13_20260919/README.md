# ZIP 输出、模型层级与自动上线验证

日期：2026-09-19。正式交付入口：`Demo_XCP_Qt/START_DEMO.cmd`。

## 本轮结果

- 构建结果最终仅保留 `<时间戳>.zip`，包内时间戳文件夹仅含 ELF、A2L、JSON。逐文件哈希验证后删除展开目录和外层重复 ELF。已有主模型 4 组、CAN 模型 7 组结果已迁移，见 `../zip_hierarchy_20260919/zip_only_migration.json`。
- Embedded Coder 根据本轮代码描述符的 Simulink SID 父链导出标准 A2L GROUP/SUB_GROUP。观测和标定使用相同模型层级树，支持组勾选、路径搜索；数值刷新保留行对象、选择及折叠状态。
- 图表支持关闭、单游标及双游标，仅测量已勾选且已绘制的可见曲线。取消勾选保留原始缓存；双游标显示时间差和值差。
- 观测页提供加载模型、上线、下线按钮，协议和端口从 ZIP/A2L 自动识别。没有文件主机地址时使用 SSH 主机；协议缺失、歧义和包内冲突禁止上线。
- 新版 EXE 已安装到正式交付目录。SHA-256：`139885a5e927c52e3135c953dac774bbff76f904646cc0691ed7e567317eb934`。

## 验证

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| Qt UI、菜单、游标及真实 TCP/UDP 回环 | 130 项通过，无失败或跳过 | `tests/qt_tests.log` |
| A2L、ZIP、部署与共享服务 | 172 项通过，无失败或跳过 | `tests/baseline_tests.log` |
| MATLAB ZIP 打包 | 6 项通过 | `../zip_hierarchy_20260919/zip_only_test_status.txt` |
| 本地交叉编译集成 | 连续两次实际构建通过 | `matlab_local_artifacts.json` |
| 两层子系统实际编译 | 观测量与标定量的路径均匹配模型 | `MATLAB_VERIFICATION.md` |
| 正式 ZIP 自动加载 | 6 个观测量、12 个标定量，UDP 17725；关闭后清理临时目录 | `zip_ui_report.json` |
| 两个窗口尺寸 | 8 张截图通过，按钮无裁切或越界 | `visual/visual_report.json` |
| 打包 EXE 与安装后启动 | Qt 和原生 DLL 正常加载，无启动错误 | `packaged_startup.json`、`installed_startup.json` |
| 正式 APP 替换 | 1340 个文件与已验证版本哈希一致 | `promotion_report.json` |

本轮未连接 Linux 目标机或执行 CAN 硬件收发，不替代之前的真机记录。旧 APP 通过正常关闭流程退出后才替换，未强制终止，未停止远端模型。

## 复验

```powershell
& .venv/Scripts/python.exe qt_xcp_host/validate_tests.py --output validation/recheck/tests
& .venv/Scripts/python.exe qt_xcp_host/validate_visual.py --output validation/recheck/visual
& .venv/Scripts/python.exe validation/app12_app13_20260919/verify_zip_ui.py
& .venv/Scripts/python.exe validation/app12_app13_20260919/verify_nested_hierarchy.py
```

MATLAB 复验方法及源码模型哈希见 `MATLAB_VERIFICATION.md`。测试用嵌套模型保留在本验证目录，未改动正式模型 SLX。
