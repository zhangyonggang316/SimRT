# 共享协议与无界面服务

本层保存可被 APP、Linux 管理工具和自动化测试共同使用的现有 Python 包，包名和调用接口保持不变。
使用时只需把 `shared/python` 加入 `PYTHONPATH`，不需要加入 `app/qt_xcp_host` 或 MATLAB 工具链目录。

| 包 | 职责 |
| --- | --- |
| `python/simrt_xcp/` | XCP TCP/UDP 客户端、ASAP2 标量解析、标定读写及命令行入口 |
| `python/pyxcp_host/` | XCP/DAQ 会话、数据模型、无界面协调逻辑、SSH 部署、目标状态、网络配置、校时及模型包验证 |

依赖方向为 `APP / Linux 工具 / 测试 -> pyxcp_host -> simrt_xcp`。
共享层不导入 Qt、Matplotlib、APP 组件、MATLAB 注册代码或编译工具，不修改 `sys.path` 来搜索这些目录。
`pyxcp_host.viewmodel` 保留已有名称，但仅协调状态、回调和工作线程，不包含界面对象。
目标机 shell/Python 命令仍由原服务生成；本次仅移动代码和调整入口路径，没有增加服务抽象或改变远端操作行为。

直接第三方依赖为 `pyxcp==0.22.32`、`paramiko==4.0.0`、`traitlets==5.11.2`，列于 `requirements.txt`。
第三方包的传递依赖由 pip 解析；完整 APP 构建继续使用 APP 自己的约束文件固定环境。
SSH 服务不要求 Qt、MATLAB、Windows DLL 或工具链存在。协议 API 和命令行使用示例见 [XCP 说明](python/README.md)。

在工程根目录执行本地回归：

```powershell
$env:PYTHONPATH = 'shared/python'
& ./.venv/Scripts/python.exe -m unittest discover -s tests/app/services -v
& ./.venv/Scripts/python.exe -m unittest discover -s tests/protocol -v
```

协议测试中的 `test_shared_boundary.py` 在独立 Python 进程中禁止导入 GUI 包，并仅提供共享源码路径，验证服务和协议包可脱离 APP、工具链独立导入。
