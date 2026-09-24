# Qt UI 重构验证

日期：2026-09-14。范围：Windows APP 从 Tkinter 迁移到 PySide6 / Qt Widgets + C++17 数据核心。
本次未连接 Ubuntu、未重新编译模型、未启停远端 ELF、未修改自启或 1 ms 调度配置。

## 结果

| 检查 | 结果 |
| --- | --- |
| 新版自动化测试 | 59 项通过，0 失败、0 错误、0 跳过，见 `test_report.json` |
| 原版服务/交互回归 | 234 项通过，0 失败、0 错误、0 跳过 |
| Qt 主窗口 | 18 项：按钮、DAQ 时序、恢复失败保护、CSV、游标、原生核心、中文编码 |
| Qt SSH/部署工作区 | 16 项：串行执行、取消、进程保护、自启、停止前 XCP guard、关窗 |
| C++ 核心 | 23 项：环形缓存、统计、插值、峰值抽样、并发、百万点容量 |
| Qt + 实际 TCP/UDP 回环 | 2 项：真实 Qt 按钮、pyxcp 通信、DAQ、在线标定、恢复、停止与断连 |
| 窗口布局 | 1320×820、1000×660 两种逻辑尺寸，三个主页面共六张截图通过边界和按钮文字检查 |
| 绘图像素 | `chart_native_10000.png` 非空白，原始数据每信号 10,000 点 |
| 冻结 EXE | 已在 Windows 启动，加载真实 Demo A2L，进入原生 Qt 页面，未自动连接目标 |

`test_report.json` 记录参与测试的源码 SHA256。`qt_tests.log` 和 `baseline_tests.log` 是对应测试明细。
原版测试仍会输出已存在的 Tk theme 销毁提示与 Pillow 弃用警告，不影响这两组测试的断言结果。
新版源码和打包运行路径不导入 Tkinter / TkAgg / PyQt。

## 截图说明

页面 PNG 是 Windows Qt 平台插件直接渲染的确定性测试夹具，**图中的资源、模型状态和曲线不是本次真机测量**。
显示缩放为 125%，文件像素尺寸为对应逻辑窗口尺寸的 1.25 倍。详细尺寸、边界和像素统计见 `visual_report.json`。
小窗口保留左右分区，部署区高度不足时使用内部滚动；不改变主页面和控件的归属。
使用 computer-use 技能另行检查了实际源码窗口与冻结 EXE 的布局和页面切换。

## 技术与验收边界

- Qt 负责窗口、控件、线程完成通知与事件循环；Matplotlib QtAgg 负责绘制曲线。
- `xcp_core.dll` 负责原始采样环形缓存、统计、游标取值、保峰值绘图抽样，缺失 DLL 会拒绝启动。
- CSV 与采样点模式使用原始样本，不将用于曲线显示的抽样或游标插值写成原始数据。
- 每信号默认 10,000 点有界缓存不变；百万点是核心容量测试，不是默认界面容量。
- 回环夹具的 1 ms DAQ 元数据不是 Windows 实时调度测试，也不是 Ubuntu model_step 的新验收证据。
- 原版 `Demo_XCP`、Python 服务源码及下位机模型文件保留不动。原归档清单 6,765 项中，仅根目录 README 和用户已更新的需求文档与旧清单不同；根目录 README 补充新版入口，不改写原清单掩盖差异。
- 新版 Ubuntu 真机联调和 MATLAB SDI 实际导入未在本次重复执行，应在部署验收时另行记录。

## 复现

```powershell
& ./.venv/Scripts/python.exe ./qt_xcp_host/validate_tests.py --output ./validation/qt_ui_rerun
& ./.venv/Scripts/python.exe ./qt_xcp_host/validate_visual.py --output ./validation/qt_ui_rerun
& ./qt_xcp_host/build.ps1
& ./qt_xcp_host/package_demo.ps1 -OutputDirectory ./Demo_XCP_Qt_rerun -QtValidationDirectory ./validation/qt_ui_rerun
```

保留现有证据，复验请使用新的输出目录。APP 重构本身不能证明所有 Ubuntu 环境下都满足硬实时截止期限。
