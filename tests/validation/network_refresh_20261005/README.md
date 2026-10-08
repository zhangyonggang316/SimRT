# IP 保存后自动刷新

日期：2026-10-05。

## 问题与修复

原网络窗口在成功保存后执行清空列表，却没有重新读取，所以必须关闭重开才能看到新 IP。

现在在同一次后台任务中依次保存配置、读取网口清单，再更新当前窗口。读取期间保留原列表，完成后按网口名称保留选择，编辑框优先显示本次应用的新 IPv4。即使为 SSH 保留了旧 IP，也不会把新输入替换为旧地址。

保存成功但后续读取失败时，显示已确认的新地址并保留其他网口，状态提示“已应用并保存；列表刷新失败”；仍可手动刷新，无需关闭窗口。保存或读取进行中禁止重复提交及关闭，SSH 操作不阻塞界面线程。

## 验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 修复前运行新回归断言 | 复现空表格、缺少刷新及编辑框丢失 | [原始失败日志](regression_before.log) |
| Qt 回归 | 151 项通过 | [测试报告](host_tests/test_report.json) |
| 共享服务回归 | 189 项通过 | [测试报告](host_tests/test_report.json) |
| Windows Qt 异步窗口流程 | 自动刷新、保留选择、刷新失败保留已确认地址均通过 | [窗口结果](dialog_result.json) |
| 新 EXE | 构建成功、启动与正常退出检查 | [构建报告](app_build_report.json)、[启动检查](app_smoke.json) |

截图：[保存成功后](after_save.png)、[保存成功但读取失败](after_read_failure.png)。截图使用合成网口数据和真实 Qt 异步 worker，未修改实机网络；不是实机配置截图。复现脚本：[verify_dialog.py](verify_dialog.py)。

## 交付

启动入口继续为 `demos/Demo_XCP_Qt/START_DEMO.cmd`。

EXE SHA256：`0e2c6082326338ba7926c555210bb8938f6ed3d952ff4e69cdb1d321d8662d35`。

旧程序备份：工作区 `tests/validation/network_refresh_20261005_previous_app/app`。本次没有修改目标机 IP、端口或模型，也没有重新编译模型。
