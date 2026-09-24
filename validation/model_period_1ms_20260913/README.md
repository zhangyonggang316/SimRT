# 实际 1 ms 模型验收

测试日期：2026-09-13。MATLAB R2024b；Windows Python 3.9.10；目标 Ubuntu 22.04.5 / PREEMPT_RT。此前实施时未修改需求原文；本次阶段归档按用户授权重新整理需求，未重新连接目标或重复硬件测试，也未改写原始报告。

## 结果分项

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 1 ms 单速率、1 ms 单任务多速率、10/100 ms 模型实际 step 周期 | 四模型通过；每个先独立运行至少 3 秒，再约 30 秒 DAQ | `period_validation_first.json` |
| 采集中标定写入、回读、恢复 | 四模型通过，DAQ 持续 | 同上 |
| 超期、跳期、XCP 错误、DAQ 完整性 | 前述四模型测试全部为 0 | 同上 |
| Runtime 夹具 | 8 场景通过，故意超期被计数，SIGTERM 正常停止 | `runtime_harness_current_run01.json` |
| 打包 APP | 默认 1 ms A2L、0.001 s DAQ、10,000 点显示和导出已实际操作 | `packaged_gui_10000_first.csv` |
| GUI 长测完整性 | **未通过全程无丢样条件**；本机 Wi-Fi 多次断连，CSV 有时间缺口 | `windows_wlan_events.json`、上述 CSV |
| 网络中断期间模型执行 | 908,614 次调用全部完成；约 908.6 秒；平均 0.999999998 ms；无超期/跳期/XCP 错误 | `packaged_gui_runtime.json` |

最后一项记录调用间隔范围为 0.582740-1.418016 ms，不是每一步精确 1 ms 的硬实时保证。GUI 缺口与 Windows 无线断连时间吻合；不要把 UDP 断网丢样解释成模型停止。采集缺失数据不能补造，连续采集需稳定有线网络并重新验收。

## 回归与交付

- APP 234 项、共享 XCP 27 项、pyxcp 二进制兼容 5 项、验证工具 56 项、RT 打包 10 项 Python 测试全部通过。
- MATLAB 既有回归 9 项通过，原始结果为 `matlab_regression.mat`（完整工程中保留）。
- PyInstaller 打包成功。当前 EXE SHA-256 为 `163A54B173E122D72DAB6AF5B4810B7E14006739A3D0A374FEA108B7399EA55B`。
- Demo 四套 ELF/A2L 哈希全部匹配，四套源码各 23 个编译输入全部存在，默认加载 `x280_rt_single`。
- 此前测试结束时，四模型和额外 GUI 模型均已停止，夹具全部退出。该轮测试没有重启系统，没有修改开机自启选择或 Windows 网络配置；这不是对当前远程状态的实时检查。
- 正式 Demo 中只保留一份 `app` 和四套当前模型；源码、测试和原始报告继续保留，缓存及重复交付副本已在归档时清理。
- 该版本每条曲线默认保留 10,000 点，超过容量淘汰最早点，密码不落盘。需求整理时新增的 1,000,000 点和记住凭据是后续目标，不计入本阶段通过项。

## 归档内容

本目录保留四套 `.slx`、`*_rt_bundle/`、`*_payload/` 及全部本阶段报告、CSV、MAT 结果。RT 源码包包含实际参与编译的运行时和模型源码；每套 payload 的 ELF、A2L、manifest 必须成套使用。

已清理可再生的 `cache/`、`codegen/`、`downloaded/`、原生非 RT `*_bundle/` 和打包暂存 `demo_package/`。上述清理不删除 `*_rt_bundle/` 或 `*_payload/`。`build_report_dwarf5.json` 保留首次构建的调试格式兼容性记录，最终测试使用 `build_report.json` 对应的 DWARF4 ELF。

报告里的本地绝对路径、远程目录、PID 和 `local_elf` 字段是历史证据，部分路径指向已清理的下载缓存。它们不应作为归档后的有效输入路径，也不能证明原远程项目现在仍存在。现成匹配 ELF 位于各 `*_payload/`，完整重建必须使用本轮新下载的 ELF 导出 A2L。

## 复现入口

完整流程以 [REPRODUCE.md](../../docs/REPRODUCE.md) 为准：先重建开发环境，在新的运行目录生成代码、转换 RT 包、SSH 编译、下载实际 ELF、导出匹配 A2L，再执行验收。不要直接对本历史目录重新运行导出或覆盖已有报告。

以下从完整工程根目录执行，`<本轮新目录>` 应替换为上述新流程产生的目录：

```powershell
.\python_xcp_host\run_tests.ps1
.\.venv\Scripts\python.exe -m unittest discover -s tools/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s x280_linux_target/tests -p test_realtime_bundle.py -v
.\.venv\Scripts\python.exe tools/validate_model_periods.py --folder <本轮新目录> --output <新的报告路径.json> --seconds 30
.\.venv\Scripts\python.exe tools/validate_runtime_harness.py --folder <本轮新目录> --output <新的夹具报告路径.json>
```

远程验证密码通过隐藏提示输入，不在文件中保存。已有报告拒绝覆盖。源码生成入口为 `tools/generate_period_models.m`，A2L 导出入口为 `tools/export_period_payloads.m`，后者必须读取新目录中的本轮构建报告及下载 ELF，不直接使用历史 `local_elf`。现成 RT 源码包的手工构建步骤见 [BUILD_TEST_1MS.md](../../Demo_XCP/BUILD_TEST_1MS.md)。

正式启动入口为 [Demo_XCP/START_DEMO.cmd](../../Demo_XCP/START_DEMO.cmd)，该独立交付包内的 `validation/` 附有本阶段主要证据。
