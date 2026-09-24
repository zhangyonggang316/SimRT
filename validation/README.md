# 验收证据索引

当前交付入口：[START_DEMO.cmd](../Demo_XCP_Qt/START_DEMO.cmd)。新机部署和复验方法见 [工程手册](../docs/README.md)。每份报告只证明该轮文件及环境，不自动证明后来修改的模型、APP 或新机器通过验收。

## 当前记录

| 目录 | 结论范围 |
| --- | --- |
| [github_upload_20260925](github_upload_20260925/README.md) | GitHub 源码发布范围、克隆副本离线回归与凭据处理 |
| [simrt_rename_20260919](simrt_rename_20260919/README.md) | SimRT 硬件注册、现用模型配置、文档同步及本地构建回归 |
| [project_cleanup_20260919](project_cleanup_20260919/README.md) | 本轮过程文件清理、源码及产物保护、部署/学习文档、清理后回归 |
| [app12_app13_20260919](app12_app13_20260919/README.md) | 当前 APP 的模型层级、单/双游标、自动端点、本地重复构建及 ZIP 输出；不包含新的 Linux 硬件操作 |
| [zip_hierarchy_20260919](zip_hierarchy_20260919/) | 11 组构建结果迁移为仅 ZIP，MATLAB 压缩测试原始记录 |
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

SSH 服务原始记录位于 `../qt_xcp_host/validation_ssh/`。历史 Wi-Fi 断连、DAQ 缺口、CAN 队列忙和有限时长计时等限制仍然有效；实时内核、一次回环或截图检查不等于长期最坏情况实时保证。
