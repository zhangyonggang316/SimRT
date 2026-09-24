# 2026-09-15 工程整理与工具链验证

唯一正式 APP：`Demo_XCP_Qt/START_DEMO.cmd`。完整操作指南为工程根目录下的 `docs/TOOLCHAIN.md`。
APP 布局和 UI-05 功能未改动；本轮更新共用 SSH 上传过滤、启动/打包入口和模型构建工具链。

## 完成内容

- 新增 `validateX280RealtimeModel`，只读检查保存状态、1 ms/10 ms/100 ms、单任务、ERT、C、目标架构、外部模式和可标定配置。
- 新增 `generateX280RealtimeBundle`，一次执行配置预检、SLX 快照、代码生成、结构化打包、RT 转换与生成回执；不自动 SSH 或启动模型。
- 构建器逐文件并行编译，默认 2 个任务；内容哈希增量缓存、编译器身份、对象校验、并发锁和原子 ELF 发布；保留 `-O2`、非 PIE 和 DWARF 4。
- 远程脚本增加离线检查、目标环境预检、独立构建目录、显式主机参数、构建回执和下载哈希核对；失败不会当作成功结果。
- A2L 导出核对模型快照、成功报告和 ELF 哈希，使用实际编译主机地址，拒绝覆盖已有 payload。
- 旧 Tk 启动/构建脚本转到 Qt；当前四套交付源码包均更新为同一构建器。

## 验证结果

| 项目 | 结果 |
| --- | --- |
| 当前用户 SLX | R2024b 成功生成 RT 源码；基本周期 0.001 s；结构检查通过 |
| MATLAB 既有测试 | 9 通过、0 失败、0 未完成 |
| Qt 自动化 | 71 通过，无跳过 |
| 共享服务回归 | 234 通过，无跳过 |
| 原生构建/RT 打包测试 | 34 通过 |
| 部署与验证工具测试 | 79 通过 |
| Qt 视觉夹具 | 1320x820、1000x660 两种逻辑尺寸，8 个页面截图无按钮文字裁切；10,000 点图形非空 |
| 新 EXE 本地启动 | 默认 A2L 成功加载；UDP 192.168.219.86:17725；6 个测量信号；未连接 SSH/XCP |
| APP 文件发布 | 1,386 个文件与新打包结果逐文件 SHA256 一致 |
| 模型文件发布 | 332 个文件与打包输入逐文件 SHA256 一致 |
| Python 依赖 | pip check 通过 |

`host_tests/` 是过程中一次失败记录：8 个旧构建测试仍假定旧单命令 API。更新测试夹具后，`host_tests_final/` 全部通过；清理后再运行结果为 `post_cleanup_tests/`。没有把原失败日志改为成功。

## Ubuntu 实测

目标：`192.168.219.86`，`zh-ThinkPad-X280`，x86-64 Linux，Python 3.10.12，GCC 11.4.0。
本轮只在新建目录编译，没有启动/停止 ELF、修改自启、改变系统实时设置或重启主机。

构建目录：`/home/zh/MATLAB_ws/builds/build_89c39b3f74c24088a268f5ace0917bfb/x280_rt_single`。

| 构建 | 编译对象 | 复用对象 | 构建器计时 |
| --- | --- | --- | --- |
| 首次，jobs=2 | 23 | 0 | 3.178 s |
| 相同目录增量构建 | 0 | 23 | 0.224 s |

这只是本机这一轮构建阶段实测，不含上传、MATLAB 生成、A2L 导出耗时，不是与旧工具的严格性能对照实验。
增量结果的 ELF 哈希与首次构建相同；新 A2L 解析到 6 个测量量、12 个标定量及 1 ms DAQ 事件，UDP 17725 和 payload 哈希校验通过。

完整工程的 `validation/toolchain_20260915/repro/` 保留 SLX 快照、cache/codegen 元数据、两级源码包、下载 ELF、新 payload、生成/构建/增量/导出报告及构建日志。
新生成 ELF 的运行调度、DAQ 连续性、算法行为和标定尚未做真机验收，因此没有覆盖默认交付的已验收 payload。

## 模型与产物来源

用户开始本轮时已修改 `Demo_XCP_Qt/models/x280_rt_single/x280_rt_single.slx`，本轮没有改写该模型。

```text
当前 SLX SHA256:
ce433a727a90e3b56be50ffb037bf89a0f63f113a31f036981da6db21cc3efda
本轮新 ELF SHA256:
62ead704d4c0de1653f0b247d9a12de58133a65e7c6d0bd35e80f243965662e4
本轮新 A2L SHA256:
2261567f8c69f23f82c51146dd596150ca5f6a011e7e17d5354cec204e52820d
新 Qt EXE SHA256:
4c73bda577acb0b837f9cf521478629ee5158e749ad51d43ad6963d51cec0b85
```

相较上一份交付模型清单，只有 5 项不同：用户已修改的 SLX，以及本轮更新的 4 份 `source/build_model.py`。
四套既有 `payload` 和其余源代码未变化。当前 SLX 不应被误认为必然对应旧 payload；重建应按新指南完整生成、编译、配套导出和验收。
历史原始 SLX/源码/payload 仍在 `validation/model_period_1ms_20260913/`。

## 清理与恢复

`cleanup_result.json` 记录 7 项移入 Windows 回收站的目录/文件，共 4,299 个文件、363,777,570 字节（约 346.93 MiB）：
旧 `Demo_XCP`、Qt `dist`/`build`/`.spec`、旧 UI 压缩包、本轮打包暂存和较早的生成试跑目录。
`app_promotion.json` 另外记录原 Qt APP 移入回收站及新版 1,386 个文件的发布校验。
没有永久擦除；恢复可在 Windows 回收站按原路径操作。恢复旧 APP 前先保留当前版本，避免同名覆盖。

源码、开发环境、需求、历史测量数据、用户最新模型和本轮最终复现元数据均保留。
本轮没有清理本机用户正在使用的 Simulink 根缓存、Python 环境或 MathWorks 工具仓库。

## 记录位置

完整工程本目录为原始证据。交付包中的 `validation/toolchain_20260915/` 仅带本说明与摘要报告，不重复携带全部 MATLAB 生成缓存。
`delivery_report.json` 是最终发布摘要；`prior_package_report.json`、`prior_app_build_report.json` 是发布前清单；`visual/` 是确定性界面夹具，不是真机波形。
