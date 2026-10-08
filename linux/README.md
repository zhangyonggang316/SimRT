# Linux 实时系统设置与优化

| 目录 | 用途 |
| --- | --- |
| `console/` | 实时机本地屏幕显示、控制台启动脚本 |
| `runtime/simrt_rt_tuning.py` | 目标机启动阶段的实时调优服务脚本 |
| `tools/` | 从上位机检查内核和资源、部署控制台、配置权限、CPU 隔离和调优 |

常用入口：

- `tools/audit_realtime_target.py`、`audit_rt_latency.py`：只读审计。
- `tools/prepare_realtime_target.py`：准备实时权限与用户服务环境。
- `tools/configure_rt_isolation.py`、`install_rt_tuning.py`：系统隔离与运行期调优。
- `tools/deploy_console_update.py`：更新实时机控制台。
- `tools/inspect_ark_resources.py`：只读查看 ARK 硬件资源。

维护脚本定位 `shared/python` 中的无界面 SSH 服务，不依赖 Qt APP 或 MATLAB。仅使用维护脚本时，安装 `linux/requirements.txt` 中的 Paramiko 即可；实时机控制台和调优脚本使用目标 Python 标准库。先通过 `--help` 查看必需参数；测试与迁移目录时不执行远程系统变更。

实测记录位于 [tests/validation](../tests/validation/README.md)，本地控制台测试位于 `tests/linux`。调度 C 运行器作为模型链接依赖保留在 `toolchain/simrt_linux_target/src`。学习路线见 [1 ms 方案](../docs/1ms_solution.md)、[50 us 优化](../tests/validation/realtime_50us_20261006/README.md)、[新机部署](../docs/NEW_MACHINE_DEPLOYMENT.md)。
