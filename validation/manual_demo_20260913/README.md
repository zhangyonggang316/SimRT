# 具体需求 3：手工 Demo 交付验证

归档注：以下为早期版本的历史记录，目录、容量、哈希与进程状态只描述当时情况。旧 Demo 和可再生中间文件已清理，当前交付及复现请从 [验收索引](../README.md) 进入；下文旧命令不等于可原样重现历史二进制。

日期：2026-09-13。此次新增内容是可分享的手工测试包和工作区生成文件清理。
之前的 Simulink R2024b 生成代码、Ubuntu GCC 编译、A2L 导出及 13 项联调检查，
见 [`../requirements_2_3/README.md`](../requirements_2_3/README.md)；本轮未重新编译模型。

## 交付入口

- [`../../Demo_XCP/START_DEMO.cmd`](../../Demo_XCP/START_DEMO.cmd)：独立桌面程序启动器。
- [`../../Demo_XCP/MANUAL_TEST.md`](../../Demo_XCP/MANUAL_TEST.md)：15 步操作、预期值和空白测试记录。
- 旧 `Demo_XCP/BUILD_TEST.md`：已收入 [历史参考 ZIP](../../docs/history/legacy_reference_sources.zip)，保留当时完整源码编译步骤。
- `Demo_XCP/payload`：已配对的 ELF、A2L 和 SHA-256 manifest。
- `Demo_XCP/source`：23 个 C 文件、48 个头文件及构建脚本；同目录包内另附 `.slx` 模型。

快速流程不依赖测试电脑安装 Python 或 MATLAB。整包复制时必须保留 `app/_internal`。
完整编译流程需要原工程、MATLAB R2024b 和相应 Coder 工具箱。
生成代码中的学术许可证声明仍适用，不扩展其使用或分享授权。

程序仅预填参数、验证产物和加载 A2L，不自动连接、上传或运行。
目标为 `192.168.219.86`，用户 `zh`；包内没有密码。每次启动使用独立远程目录。
通过 computer-use 技能规定的窗口检查流程核对了打包版标题、UDP 17725、路径、空密码框和未连接状态。
完整编译手册依据本地 R2024b 官方帮助核对 `slbuild` 与 `Simulink.fileGenControl` 调用。

## 验证结果

`python_xcp_host/run_tests.ps1` 全部通过：111 项上位机测试、25 项共享后端测试、
5 项真实套接字与官方示例测试，合计 141 项；`compileall` 与 `pip check` 也通过。

[`report.json`](report.json) 中 11 项真机流程检查全部通过。
执行方式为 `validate_manual_demo.py` 驱动与手工操作相同的 APP 回调，
覆盖预填、连接、上传、资源与模型发现、模型启动、动态观测、CSV、
标定为 0.75、原值恢复、停止前自动恢复与断开、ELF 回传以及 SSH 断开。
这不是测试人员手工签字验收，因此交付手册中的测试记录未代填。

远程保留目录：`/home/zh/MATLAB_ws/manual_demo_20260913_002513_b87f5f30`。
测试模型已停止，测试 SSH 会话已断开；没有删除远程文件，也没有配置 sudo。
证据包括 [`app.log`](app.log)、[`manual_observation.csv`](manual_observation.csv) 和 `downloaded.elf`。
本轮自动观测收集至少 30 个样本；手册要求测试人员另做至少 20 秒观测。
UDP 轮询不是硬实时或零丢包保证，其他模型必须使用自己匹配的 ELF/A2L 验收。

复现自动流程（仅在确需真机操作时运行，密码隐藏输入）：

```powershell
cd 'C:\DataSave\03matlabUbuntu\01AI ToolLinux'
.\.venv\Scripts\python.exe .\python_xcp_host\validate_manual_demo.py --demo .\Demo_XCP --output .\validation\manual_demo_retest
```

`PyXCPHost.exe` SHA-256：
`4ca5fe688d8125e4bdeea5da145a6936811ea902c18fdcaa6ae99359202a6051`。

基准 ELF SHA-256：
`8c309c5d6a369013a8e4a11e3bb73c258fbe447b8d38ce4e676c68a9f2317496`。

## 文件清理

25 项目标共 32,107,359 字节（30.62 MiB），均已移入 Windows 回收站，可恢复，未永久删除。
具体路径与逐项结果见 [`../cleanup_20260913.json`](../cleanup_20260913.json)。
包括两个应用的 PyInstaller 构建中间目录、项目 Python 字节码缓存、Simulink 缓存、
临时下载目录，以及缺少早期 XCP 适配器的过期源码压缩包。

保留 `.python`、`.venv`、原始工程和模型、应用分发包、完整源代码、
`requirements_2_3/codegen` 中用于同轮 A2L 导出的元数据、现行源码包以及全部真机证据。
执行前确认没有相关构建进程；目标限定在工作区且拒绝符号链接。
清理工具 `tools/cleanup_generated_20260913.ps1` 默认仅列出目标，只有 `-Apply` 才移入回收站。
不要重复运行而覆盖本次清理报告。

需求文档保持原样，SHA-256：
`4867f526f4209d7ed59ee49478f4a006a04f054c36c03b131d2ca68fd273911f`。
