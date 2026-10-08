# SimRT

本目录保存 SimRT 上位机界面、界面生命周期及 C++ 数据核心。Qt Widgets 界面位于
`qt_host/`；无界面的 XCP、SSH、部署和目标状态服务位于 `../../shared/python/pyxcp_host/`，
底层协议库位于 `../../shared/python/simrt_xcp/`。两者均不依赖 APP 或 Qt。
服务测试位于 `../../tests/app/services/`。
正式 APP 位于 `../distribution/`，模型预设位于 `../../demos/Demo_XCP_Qt/`。
双击 `../START_APP.cmd` 或 Demo 内的 `START_DEMO.cmd` 可加载相同预设，默认不连接目标机。

## 技术边界

- Python 3.9.10 x64 + `PySide6-Essentials==6.8.3`，提供 Qt Core / GUI / Widgets。
- C++17 `xcp_core.dll` 保存原始采样、滚动统计、游标插值和保峰值曲线抽样；Python 使用 ctypes 调用 C ABI。
- 曲线使用 Matplotlib 3.9.4 的 QtAgg 画布嵌入 Qt Widgets；不再使用 TkAgg。原始数据、统计、游标取值和绘图抽样均来自 C++ 核心。
- 每信号默认保留 1,000,000 个原始点；曲线和点显示使用可见区间的保峰值抽样，CSV 在后台导出完整缓存。
- `pyxcp==0.22.32` 处理 XCP，`paramiko==4.0.0` 处理 SSH；APP 部署经清单和远端哈希验证的本地 ELF/A2L。
- 可选记忆 SSH 凭据，使用当前 Windows 用户的 DPAPI 加密；成功登录后保存，取消勾选删除，启动不自动连接。
- 模型 ZIP 在 APP 私有临时目录内解压，校验三个文件及清单 SHA256 后自动识别 ELF/A2L；关闭 APP 清理缓存，上传使用解压产物。兼容已有三文件目录。
- XCP 目标地址优先使用实时机页面非空的“Ubuntu 主机”输入，顶部端点与实际连接同步；输入为空时依次使用 ZIP 的 `TargetAddress`、A2L 的 `ADDRESS`。协议和端口仍从文件识别并校验一致性；只换目标 IP 无需改包。XCP 在线时可修改主机输入，回车或离开输入框后保存，并在恢复标定、断开旧会话后连接新地址；连接切换期间输入只读。
- 本项目 XCP 标准默认端口为 UDP `5555`、TCP `17725`，当前模型使用 UDP。APP 遵循加载文件声明的实际端口；旧端口模型应重新构建匹配的 ELF/A2L/manifest ZIP，不能只改旧清单或 A2L。
- 连接、切换目录及文件变化时加载模型清单；资源与当前进程状态后台静默更新，保留行、选择和滚动位置。监测期间点击的 SSH 命令会排队执行。
- Qt 绘图刷新、XCP DAQ、Ubuntu 模型的 1 ms 实时执行是不同的周期。更换 UI 不会修改 Ubuntu 调度配置。
- 缺失或 ABI 不匹配的 C++ DLL 会明确报错，不静默退回 Python 实现。

`PySide6-Essentials` 是 Qt 官方提供的 PySide6 基础模块分包，不需要安装体积较大的 Addons。
参见 [Qt 包说明](https://doc.qt.io/qtforpython-6/package_details.html)。

## 目录

| 路径 | 内容 |
| --- | --- |
| `main.py`、`qt_host/` | 新版 Qt 前端和 ctypes 适配层 |
| `../../shared/python/pyxcp_host/` | XCP、DAQ、A2L、标定、SSH、产物验证和目标机业务服务 |
| `../../tests/app/services/` | 共享服务、协议回环和部署验证测试 |
| `native/` | C++17 源码、C ABI 头文件及编译器说明 |
| `qt_host/native_bin/xcp_core.dll` | 运行所需的原生核心 |
| `../../tests/app/ui/` | Qt 与原生核心测试 |
| `../../tests/protocol/` | XCP 协议后端测试 |
| `requirements.txt` | 固定的运行/构建依赖，复用归档依赖约束 |
| `constraints-archive.txt` | 当前 APP 使用的共享依赖版本约束 |
| `run.ps1` | 源码启动，默认读取当前 Demo_XCP_Qt 的模型预设 |
| `build_native.ps1` | 仅构建 C++ 数据核心 |
| `build.ps1` | 构建 C++ 核心与 `dist/SimRT/SimRT.exe` |
| `qt_host/assets/simrt.ico`、`version_info.txt` | SimRT 应用图标与 Windows 版本资源 |
| `package_demo.ps1`、`demo/` | 生成新的暂存交付目录，验证后再替换正式交付 |
| `run_service_tests.ps1`、`run_service_tests.cmd` | 服务测试、XCP 后端回环与依赖检查 |
| `../../demos/app_examples/`、`../../tests/validation/app_ssh/` | 历史 SSH 服务诊断夹具及记录，不是额外 APP |

## 环境复现

在完整工程根目录运行。已有 `.venv` 时不要重新创建；需要新环境时使用已归档的 Python 3.9.10 x64：

```powershell
& ./.python/3.9.10/python.exe -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r ./app/qt_xcp_host/requirements.txt
& ./.venv/Scripts/python.exe -m pip check
```

C++ 编译器是项目内的 LLVM-MinGW 20250709 / Clang 20.1.8 x64 UCRT，默认位置为
`toolchain/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/bin/clang++.exe`，不依赖系统 PATH。
完整工具链已在工作区准备好；重新获取时使用官方发布包并核验 SHA256 后解压：

- [LLVM-MinGW 官方发布页](https://github.com/mstorsjo/llvm-mingw/releases/tag/20250709)
- 包名：`llvm-mingw-20250709-ucrt-x86_64.zip`
- SHA256：`82babcd6aae4dc3606e8e0471d816989c384b4bf86a139f184a8b4a1b2c2758d`

仅替换编译器路径时，可执行 `build_native.ps1 -Compiler '完整路径/clang++.exe'`；这仍须是兼容的
x64 Windows C++17 工具链。C++ 运行库静态链接到 DLL，APP 使用者不需要安装编译器。

## 源码启动与测试

每次成功连接 SSH 后，后台校时任务等待模型停止，以及至少三次、跨四秒的 CPU 与各核心低于 50% 的采样。任务执行前再次检查目标机和连接延迟；使用上位机当前 UTC 时间戳及 Qt 提供的 IANA 时区。两秒以内偏差保留系统时钟，仅同步时区；较大偏差提交 chrony 校正并保留 NTP。忙时延后，失败最多重试三次；断开、断线或关闭 APP 清除待处理任务及内存中的会话密码。

```powershell
& ./app/qt_xcp_host/build_native.ps1
& ./app/qt_xcp_host/run.ps1
$env:PYTHONPATH = 'app/qt_xcp_host;shared/python'
$env:QT_QPA_PLATFORM = 'offscreen'
& ./.venv/Scripts/python.exe -m unittest discover -s tests/app/ui -v
& ./.venv/Scripts/python.exe -m unittest discover -s tests/app/services -v
Remove-Item Env:QT_QPA_PLATFORM
```

`run.ps1 -DemoDirectory '另一个完整 Demo 目录'` 可以选择其他预设。不会自动连接目标机。
完整 Qt 测试依赖原生 DLL 已存在；测试失败不能作为已验证版本交付。

## 构建与打包

```powershell
& ./app/qt_xcp_host/build.ps1
& ./app/qt_xcp_host/package_demo.ps1 -OutputDirectory ./tests/validation/app_package_new
```

`build.ps1` 只重建本目录下生成的 `build/`、`dist/` 和 `.spec`，不运行 pip 安装，不修改归档 APP。
使用已有原生 DLL 时可加 `-SkipNativeBuild`。构建成功会检查 Qt Windows 插件、C++ DLL 和
旧 GUI 运行库排除情况，记录 `dist/SimRT/build_report.json`；该报告不是 GUI 或真机验收结论。
构建使用 `qt_host/assets/simrt.ico` 作为 EXE 图标，并嵌入 `version_info.txt` 中的 Windows 版本资源。

`package_demo.ps1` 从 `../../demos/Demo_XCP_Qt/` 读取模型基线，默认使用新构建的 `dist/SimRT/`。
也可显式选择已发布 APP。必须指定新的暂存输出路径，拒绝覆盖正式交付或向模型目录内部打包：

```powershell
& ./app/qt_xcp_host/package_demo.ps1 -ApplicationDirectory ./app/distribution -OutputDirectory ./tests/validation/app_package_new
```

脚本要求当前交付仅含 `simrt_rt_single` 一套 1 ms 模型，从 `demo.json` 读取选定结果目录。
只复制 SLX 和选定构建 ZIP，逐文件比对 SHA256；ZIP 内仅含时间戳文件夹及 ELF、A2L、manifest，不复制展开目录、中间源码、缓存或其它编译轮次。
默认预设 `demo.json` 沿用原版，入口为 `app/SimRT.exe --demo-dir ...`。
用 `-QtValidationDirectory '验证证据目录'` 可同时打入新 Qt 验收记录，历史模型报告另存，避免混淆。

导出的便携包是独立交付边界，保持 `app/`、`models/`、`demo.json`、`validation/` 的自包含布局；
它不会改变完整工程中 APP、工具链、Linux、测试与 Demo 的分类目录。包内用户运行 `START_DEMO.cmd`，不需要安装 Python、Qt 或 MATLAB。必须保留整个
`app/_internal/`，不能只分发 EXE。Qt 与相关第三方组件的版本元数据/随包许可证保留在交付包中；
对外发布还需按 [Qt for Python 许可证说明](https://doc.qt.io/qtforpython-6/licenses.html) 核对对应发行义务。

完成验证并更新正式交付后，清理暂存包、`build/`、`dist/` 和自动生成的 `.spec`，工程只保留正式 APP 一份。
模型本地交叉编译与 SSH 部署见 `../../docs/TOOLCHAIN.md`。完整工程的正式运行目录为 `app/distribution/`，须保留其中的 `_internal/`。下列历史记录保留原版实现背景，现行共享层边界见 `../../shared/README.md`。

## 当前验证记录

2026-09-19 当前版本：模型层级树、单/双游标和文件自动端点已交付，130 项 Qt 与 172 项服务测试通过。工程整理后再次通过同一回归，正式 EXE 未改变；构建缓存和暂存 APP 已清理。新机部署见 [部署指南](../docs/NEW_MACHINE_DEPLOYMENT.md)，源码导读见 [技术路线](../docs/ARCHITECTURE.md)，清理与保留范围见 [目录规则](../docs/PROJECT_LAYOUT.md)。下列记录按历史阶段保留。

2026-09-19：新增模型 ZIP 内部解压、三文件自动识别与哈希校验；所有右键菜单补齐图标并验证实际 QAction 操作；模型目录按需扫描，资源监测不再周期性禁用按钮或重建列表。125 项 Qt、159 项服务测试全部通过；真实模型 ZIP 加载识别 6 个观测量和 12 个标定量，8 张界面截图检查通过。编译端通过 ZIP 单测和两次实际本地编译，10 个现有时间戳目录补齐 ZIP，删除两处经哈希核对的外层 ELF。见 `../validation/zip_app_20260919/`；本轮未连接目标机，不将菜单夹具测试等同于真机启停、删除或重启验收。

2026-09-18：模型列表右键新增“删除模型”，确认后删除已停止模型的远程父目录并清除匹配的开机自启配置；删除期间禁止并发操作，远端复查目录范围、符号链接、其它 ELF 和运行进程。服务 159 项测试通过；Qt 96 项回归中旧菜单替身补齐图标接口后，对应 UI-05 的 10 项复测通过，其余 86 项已通过。右键菜单、实际确认框取消操作及新版 EXE 本地启动检查通过。记录见 `../validation/model_delete_20260918/`；未进行真实目标机删除测试，未启动 MATLAB。

2026-09-16 目录合并：业务服务和服务测试已移入本目录，原独立目录已删除。合并后 Qt 90 项、服务 135 项、XCP 后端 27 项、相关部署工具 42 项测试通过；入口脚本语法、依赖约束与 `pip check` 通过。EXE 已重新构建并通过本地启动检查，分发打包已适配三文件结果目录。记录见 `../validation/qt_merged_final_20260916/` 和 `../validation/flat_artifacts_qt_20260916/`；本轮未连接实际目标机。

2026-09-16：本地产物部署、Windows 加密凭据记忆、每信号百万点缓存、后台完整 CSV/SDI 导出已实现。仅保留一套 1 ms 模型和 Qt APP；清理后 Qt 90 项、共享服务 135 项测试通过，8 张界面截图通过。当前记录见 `../validation/single_model_qt_20260916/`；本地 Ctrl+B 构建证据见 `../validation/local_ctrlb_final_20260916/`。下面为历史版本记录。

2026-09-15：仅保留 `Demo_XCP_Qt` 一份 APP，旧启动器转到 Qt；SSH 上传过滤新增的编译缓存和构建回执。
Qt 71 项、共享服务 234 项回归通过，8 张界面夹具截图通过；新版 EXE 本地启动和默认 A2L 加载检查通过。
最新结果见 `../validation/toolchain_20260915/README.md`。本轮没有启动新编译 ELF，也没有用新 APP 做真机测量/标定验收。

以下保留 UI-05 阶段结果：

2026-09-14 UI-05：部署与运行日志统一到“实时机 / 诊断日志”，支持读取运行日志、复制全部、清空显示、保存日志。
读取优先使用模型列表中选中的 ELF，否则使用部署页配置的 ELF。移除启动参数输入，启动及设置自启均不传附加参数。
模型部署页不再提供刷新状态、读取日志、取消任务按钮；后台自动刷新 ELF 状态，关闭 APP 时仍保留内部任务取消和安全退出处理。

新版 69 项自动化测试与原版 234 项回归测试全部通过，无跳过。
新版包括 C++ 核心 23 项、Qt 部署 16 项、主窗口 18 项、实际 TCP/UDP 回环 2 项、UI-05 专项 10 项。
模型部署、诊断日志、观测、标定在 1320×820 和 1000×660 逻辑尺寸下检查，共 8 张界面截图。
本次不重复 Ubuntu 真机和 MATLAB SDI 实际导入验收，模型和 1 ms 调度不变。
详见 `../validation/ui05_20260914/README.md`。此前 Qt 初版记录保留在 `../validation/qt_ui_20260914/`，不能借用历史 GUI 报告证明本版真机通过。

完整回归和截图复现：

```powershell
& ./.venv/Scripts/python.exe ./app/qt_xcp_host/validate_tests.py --output ./tests/validation/qt_ui_rerun
& ./.venv/Scripts/python.exe ./app/qt_xcp_host/validate_visual.py --output ./tests/validation/qt_ui_rerun
```
