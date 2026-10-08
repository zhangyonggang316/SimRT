# 验收证据索引

当前交付入口：[START_DEMO.cmd](../../demos/Demo_XCP_Qt/START_DEMO.cmd)。新机部署和复验方法见 [工程手册](../../docs/README.md)。每份报告只证明该轮文件及环境，不自动证明后来修改的模型、APP 或新机器通过验收。

## 当前记录

| 目录 | 结论范围 |
| --- | --- |
| [polar_comparison_20261007](polar_comparison_20261007/README.md) | PolarDriver 可读构建流程对照、配置保留、构建前检查、注册去重及 DAQ 参数统一；本轮仅本地验证 |
| [rs485_com56_20261007](rs485_com56_20261007/README.md) | COM5/6 双向模型、R2024b 本地构建及 APP 导入；候选端口原生测试发送后无接收，物理通信尚未通过 |
| [dio_test_20261007](dio_test_20261007/README.md) | 已停止板载 GPIO/DIO 适配与硬件测试；保留万用表测试模型、桌面仿真及本地构建证据，实际电平未验证 |
| [ctrlb_20261007](ctrlb_20261007/README.md) | R2024b Hardware 构建按钮恢复、实际工具栏动作完成本地 XCP 模型构建；未做新的实时机验收 |
| [simrt_target_20261007](simrt_target_20261007/README.md) | 改名后真机部署、120 秒 XCP/标定、周期及显示通过；UDP 有 40 个缺口，整体未通过并恢复原模型 |
| [simrt_migration_20261007](simrt_migration_20261007/README.md) | SimRT 全部源码标识迁移、R2024b 注册及构建、APP 回归与存档同步 |
| [realtime_50us_20261006](realtime_50us_20261006/README.md) | 旧模型超过 14 小时后未满足 ±50 us；本轮 CPU 隔离、500 us 提前唤醒及分阶段复验，长期验收单独记录 |
| [project_cleanup_20261006](project_cleanup_20261006/README.md) | 缓存和重复展开模型清理、保护文件哈希一致、完整版本保存与学习入口 |
| [realtime_20261006](realtime_20261006/README.md) | 1 ms 调度短时验证通过、累计时间显示更新；UDP DAQ 无丢样尚未通过 |
| [simrt_library_20261006](simrt_library_20261006/README.md) | R2024b 一个 SimRT 根库、五个子库及 13 个模块的实际浏览器验收 |
| [ark_io_20261005](ark_io_20261005/README.md) | ARK 库安装、软件测试、本地编译与硬件只读清单；板载 DIO 驱动尚未接通 |
| [project_cleanup_20261005](project_cleanup_20261005/README.md) | 重复 APP 暂存交付及缓存清理，保留最新回退副本与模型证据 |
| [startup_network_time_20261005](startup_network_time_20261005/README.md) | 静态 IP 重启保留、空闲校时和实际启动优化记录 |
| [simrt_rename_20260919](simrt_rename_20260919/README.md) | SimRT 硬件注册、现用模型配置、文档同步及本地构建回归 |
| [project_cleanup_20260919](project_cleanup_20260919/README.md) | 本轮过程文件清理、源码及产物保护、部署/学习文档、清理后回归 |
| [app12_app13_20260919](app12_app13_20260919/README.md) | 当前 APP 的模型层级、单/双游标、自动端点、本地重复构建及 ZIP 输出；不包含新的 Linux 硬件操作 |
| [zip_hierarchy_20260919](zip_hierarchy_20260919) | 11 组构建结果迁移为仅 ZIP，MATLAB 压缩测试原始记录 |
| [zip_app_20260919](zip_app_20260919/README.md) | ZIP 加载、右键菜单图标和行为、模型列表稳定性 |
| [tc1013_can_20260919](tc1013_can_20260919/README.md) | 已有 TC1013 经典 CAN/CAN FD 双向真机回环及驱动安装证据 |
| [tc1013_can_20260918](tc1013_can_20260918/README.md) | CAN System 对象、生成接口和 SDK 适配的早期验证 |

当前仅交付一套 1 ms 主模型及 Python/Qt APP；CAN 驱动示例和其测试证据单独保留。旧暂存交付包、APP 备份、Python/Simulink 缓存已在本轮清理，正式 APP、SLX、ZIP、源码、生成元数据及报告继续保留。删除明细和哈希见本轮清理记录。

## 历史记录

| 目录 | 历史内容 |
| --- | --- |
| [model_delete_20260918](model_delete_20260918/README.md) | 模型删除菜单及目录保护 |
| [single_model_qt_20260916](single_model_qt_20260916/README.md) | 统一到 1 ms 主模型和 Qt APP |
| [toolchain_20260915](toolchain_20260915/README.md) | 向本地交叉编译迁移时的构建与整理记录 |
| [ui05_20260914](ui05_20260914/README.md) | 日志整合与控件调整 |
| [qt_ui_20260914](qt_ui_20260914/README.md) | Qt 初版和 C++ 核心迁移 |
| [model_period_1ms_20260913](model_period_1ms_20260913/README.md) | 当时四套模型的 step、DAQ、标定和长测，非当前交付模型集合 |
| [archive_20260913](archive_20260913/README.md) | 早期归档与路径复核 |
| [pyxcp_02232](pyxcp_02232/README.md) | 固定 pyxcp 版本及回环记录 |
| [requirements_2_3](requirements_2_3/README.md) | 早期 10 ms 集成模型联调，部分夹具仍被验证器读取 |
| [requirements_update_20260913](requirements_update_20260913/README.md) | 普通内核/RT 对照及原始 XCP 错误记录 |
| [rt_boot_20260913_121920](rt_boot_20260913_121920/README.md) | 重启、自启与恢复原状态 |
| [ui_refresh_20260913](ui_refresh_20260913/README.md) | 早期 UI 刷新检查 |
| [manual_demo_20260913](manual_demo_20260913/README.md) | 早期手工验收 |

历史 JSON、MAT、CSV、日志和截图不改写为新的成功结论。报告中的已删除暂存目录或旧绝对路径仅作溯源；复验应生成新报告，重新构建后必须使用同轮配套文件。

SSH 服务原始记录位于 `../tests/validation/app_ssh/`。历史 Wi-Fi 断连、DAQ 缺口、CAN 队列忙和有限时长计时等限制仍然有效；实时内核、一次回环或截图检查不等于长期最坏情况实时保证。
