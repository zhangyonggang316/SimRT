# 模型 ZIP 与 APP-10 / APP-11 验证

日期：2026-09-19。

## 已交付行为

- Ctrl+B 本地编译发布 `<模型>_local/<时间戳>/`，目录直接包含 ELF、A2L、XCP manifest JSON 三个文件。同级生成 `<时间戳>.zip`，ZIP 内保留这一层文件夹；验证解压内容和哈希后删除模型根目录的重复 ELF。源码与报告继续保存在中间构建目录。
- APP 通过“本地模型包 (ZIP)”选择 ZIP，后台解压至私有缓存，校验清单与 SHA256，自动识别 ELF 并加载配套 A2L/协议/端口。SSH 上传解压后的文件，退出清理缓存。损坏包、路径穿越、链接、重复文件、额外内容及超限文件被拒绝。
- 模型、信号、图表、统计/游标、标定及日志右键菜单带图标；针对实际 QAction 验证了选择、启停、开机自启、删除、复制、刷新、可见性、子图、曲线模式、游标、标定回调和图像导出。
- 修复详情表未选中右击行、刷新丢失选择、菜单对象随选择变化和无可执行内容时仍启用命令的问题。
- 模型清单仅在连接、切换目录、手动刷新及上传/删除后扫描。资源和当前部署进程状态静默监测，不反复重建未变化的行，不周期性禁用按钮；监测期间的操作排队，菜单展开期间延后列表更新。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| Qt、原生核心、协议回环及 APP 测试 | 125 项通过，0 失败、0 跳过 |
| 共享通信、SSH、监测及部署服务 | 159 项通过，0 失败、0 跳过 |
| MATLAB ZIP 单测 | `tX280ArtifactArchive` 4 项通过 |
| MATLAB 本地编译集成 | `tX280LocalArtifacts` 1 项通过；同一临时模型实际编译两次，验证删除外层 ELF 后可再次构建及定位发布 ELF |
| MATLAB Code Analyzer | 本次 6 个 MATLAB 文件无检查消息 |
| 真实模型 ZIP / A2L | 自动识别 6 个观测量、12 个标定量；关闭窗口后私有解压目录清除 |
| Qt 界面 | 1320x820、1000x660 下共 8 张截图检查通过；按钮未截断或越界，图表像素检查通过 |
| 历史正式产物迁移 | 10 个时间戳 ZIP 通过 CRC、内容、SHA256；两处外层 ELF 经匹配核对后删除；两份 SLX 哈希未变化 |
| 分发打包 | 验证复制 SLX、ELF、A2L、JSON、ZIP 共 5 个模型文件 |
| EXE 安装 | 1340 个程序文件与暂存交付逐个比对通过；正式 EXE 启动检查通过 |

正式入口：`../../Demo_XCP_Qt/START_DEMO.cmd`。

EXE SHA256：`340d8af9f7ec6d0d27f2de631f5bf065ccd5d5ef6ee590dfb35e46e98d3e4cea`。

测试报告：[tests/test_report.json](tests/test_report.json)。界面报告：[visual/visual_report.json](visual/visual_report.json)。真实 ZIP 加载：[zip_ui_report.json](zip_ui_report.json)、[zip_loaded.png](zip_loaded.png)。模型菜单：[model_context_menu.png](model_context_menu.png)。产物迁移：[artifact_migration.md](artifact_migration.md)、[artifact_migration.json](artifact_migration.json)。正式安装：[promotion_report.json](promotion_report.json)、[installed_startup.json](installed_startup.json)。

本次复用已存在的 MATLAB 会话进行必要的构建验证。APP 测试和截图使用本地夹具；未连接或修改实际 Linux 目标机。本次结果不代表新版 APP 的真机启停、远程删除、重启自启或实时性能已重新验收。

构建日志中的 `pyxcp.recorder.converter` 可选依赖警告不影响本 APP 使用的 XCP 服务与自身 CSV 导出；本轮 CSV 测试通过。PyInstaller 完成打包，EXE 的 Qt/C++ 模块及正式启动另行核验。

## 复验

```powershell
& ./.venv/Scripts/python.exe ./qt_xcp_host/validate_tests.py --output ./validation/zip_app_rerun
& ./.venv/Scripts/python.exe ./qt_xcp_host/validate_visual.py --output ./validation/zip_app_rerun
& ./.venv/Scripts/python.exe ./validation/zip_app_20260919/verify_zip_ui.py
```

MATLAB 中在保存并关闭 `x280_rt_single` 后执行；集成测试会在临时目录编译模型副本：

```matlab
addpath('x280_linux_target');
results = runtests({'x280_linux_target/tests/tX280ArtifactArchive.m', ...
    'x280_linux_target/tests/tX280LocalArtifacts.m'});
assertSuccess(results);
```

正式安装已完成。安装后清理 `qt_xcp_host/build/`、`qt_xcp_host/dist/`、`qt_xcp_host/QtXCPHost.spec` 和本目录 `staging_delivery/` 的命令被自动审批策略拒绝，工具仅返回 `blocked by policy`，因此这些生成副本仍保留。本目录还保留验证证据及 `replaced_app_files/` 中本次替换的旧文件用于回退。日常只使用 `Demo_XCP_Qt/START_DEMO.cmd`。
