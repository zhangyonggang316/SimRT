# 单模型 Qt 交付记录

日期：2026-09-16。工程交付仅保留 `x280_rt_single` 一套 1 ms 单任务单速率模型，以及 Python/PySide6 Qt APP。
正式入口为 `../../Demo_XCP_Qt/START_DEMO.cmd`。

## 清理内容

- 删除其它三套模型在交付包和历史构建目录中的 SLX、源码包、ELF/A2L、配套清单及生成缓存。
- 删除旧 Tkinter 界面、独立启动/构建/打包入口、专属界面测试、手册和字节码。
- 删除历史非 Qt APP 源码 ZIP、临时交付包及 PyInstaller 重复 EXE。
- 保留 Qt 共用的 `python_xcp_host` 业务与通信服务、C++ 核心、开发工具及必要历史测试报告。
- 构建、打包和当前验收脚本统一只接收 `x280_rt_single`。历史报告中的已删除路径仅供追溯。

目录、模型和生成产物的清理使用 Windows 回收站；旧 Tk 源码通过补丁删除。
清理范围为本地工程，本次没有启动 MATLAB、连接 SSH 或修改目标机进程及自启配置。

## 验证

| 检查 | 结果 |
| --- | --- |
| Qt 与 C++ 核心回归 | 90 项通过，无跳过 |
| 共享业务与通信服务 | 135 项通过，无跳过 |
| 工具脚本回归 | 89 项通过 |
| Qt 界面截图 | 1320×820、1000×660 两种逻辑尺寸，共 8 张通过 |
| 模型文件复制校验 | 82 个文件 SHA-256 一致 |
| SLX 结构检查 | FixedStep=0.001、EnableMultiTasking=off、GenCodeOnly=off、本地工具链 |
| EXE 内嵌模块检查 | Qt 模块存在，无 Tkinter、旧 pyxcp_host.ui/app 或 PyQt 模块 |
| 打包 EXE 隐藏启动 | Qt Widgets 和 C++ DLL 加载成功，无启动错误日志；测试清理结束进程 |

本次模型使用已完成本地 Ctrl+B 交叉编译和真机验证的同轮 SLX、RT 源码与 payload。
原始证据在 `../local_ctrlb_final_20260916/build_report.json` 和 `../requirements_20260916/local_workflow.json`。
交付包 `validation/model_baseline` 明确记录从原报告选出的唯一模型记录，不将摘录伪记为新的真机测试。
该模型 30 秒 DAQ、3 秒 SSH 断开自主运行、标定写入/回读/恢复均通过；step 平均间隔为 0.999999984 ms，超期和跳期为 0。

## 文件索引

- `delivery_report.json`：本轮交付检查汇总。
- `host_tests/`：回归日志、计数、源码哈希、截图和视觉检查报告。
- `packaged_startup.json`：实际 EXE 启动记录及其哈希。
- `model_cleanup.json`：已删除的模型/归档路径。
- `legacy_cache_cleanup.json`：旧界面字节码和空目录清理记录。
- `promotion.json`：正式交付替换和重复构建清理记录。

`package_report.json` 的 baseline 路径指本次临时组包来源，验证并发布后已清理；其逐文件哈希仍可用于检查正式交付。
软实时短测、回环测试与界面截图各有验证范围，不能替代长期或任意负载验收。
