# 蓝色导航与 SDI 风格观测验证

归档注：以下为早期版本的历史记录，目录、容量、哈希与进程状态只描述当时情况。旧 APP 和 Demo 副本已清理，当前交付及复现请从 [验收索引](../README.md) 进入；下文旧命令不等于可原样重现历史二进制。

日期：2026-09-13。对应更新需求第 2 部分第 8、9、10 项。
本次不重新生成模型或编译 ELF，继续使用已配对的 Simulink R2024b 真机产物。

## 交付

本阶段交付目录已退役。当前入口为 [Demo_XCP_Qt/START_DEMO.cmd](../../../demos/Demo_XCP_Qt/START_DEMO.cmd)，操作与构建见 [当前手册](../../../demos/Demo_XCP_Qt/MANUAL_TEST.md)及 [工具链](../../../docs/TOOLCHAIN.md)。下文界面功能仅描述当时版本。

顶层导航依次是“实时机”“观测”“标定”。“实时机”集中 A2L/XCP 设置，
包含“资源与模型”“SSH 部署”“诊断日志”子页。现有停止前恢复标定、进程身份校验和密码不落盘机制保持不变。

当时新版使用 Matplotlib、NumPy、Pillow 和 Tk。当前工程已采用 PySide6 Qt；应完整保留当前交付目录所需文件，不按历史包结构重新拼装。

## 图形功能

内嵌观测页使用 Matplotlib 3.9.4 的 Tk 后端，提供图标工具栏、框选/滚轮缩放、平移、
视图前进后退、自动跟随与适应、1x1/2x1/2x2 子图及共享时间轴。
信号可调整颜色、显示状态及所属子图；双游标支持拖动、精确时间输入、值差和时间差。
插值值在表格中标记，不在数据范围内时显示 `--`，不伪造外推数据。
PNG、CSV 和统计使用真实缓存数据；显示隐藏不改变原始导出数据。

当时内嵌图表提供可选“MATLAB SDI”入口用于运行对比、容差分析和回放，当前 APP 已移除此入口。
以下导出行为是历史实现记录：
该入口需要本机 MATLAB/Simulink，快速 Demo 的 XCP/SSH/标定不需要 MATLAB。
导出创建新的 `capture.json` 和 `open_in_sdi.m`，信号名称作为数据，不拼接到执行代码中；
导入不清除已有运行或偏好。只有当前有限缓存会导出，不代表完整采集历史。

设计依据为 [Simulation Data Inspector](https://www.mathworks.com/help/simulink/slref/simulationdatainspector.html)
和 [Inspect Simulation Data](https://www.mathworks.com/help/simulink/ug/visual-inspection-of-signal-data.html)，
并通过 matlab-read-doc 技能核对了本机 R2024b 的 `Simulink.sdi.createRun`、`view` 和子图帮助。

## 测试结果

`python_xcp_host/run_tests.ps1` 全部通过：148 项应用测试、25 项共享后端测试、
5 项实际套接字/原生扩展测试，共 178 项；另通过 `compileall` 和 `pip check`。
新增回归覆盖导航顺序、A2L 归属与宽度、切换菜单时的稳定尺寸、原生 SDI 入口取消、
鼠标缩放/平移、游标数值和拖动、图像非空、有限缓存和最小窗口布局。

[`report.json`](report.json) 的 15 项真机流程检查全部通过。
Ubuntu 为 `192.168.219.86`；远程目录为
`/home/zh/MATLAB_ws/manual_demo_20260913_014401_8e05f500`。
使用 APP 实际回调执行上传、模型发现和启动、双信号采样、分图、游标、导出、
标定为 0.75、原值恢复、停止前自动恢复与断开、ELF 回传校验以及 SSH 断开。
测试模型已停止，目录和日志保留；没有删除已有远程项目。

证据：[`observation.png`](observation.png)、[`manual_observation.csv`](manual_observation.csv)、
[`app.log`](app.log)、`downloaded.elf`。computer-use 窗口检查确认了实际动态双曲线和新打包界面。
本轮脚本驱动验证不代替测试人员手工签字；手册中的验收表仍为空。

原生 MATLAB 导入的 Python 层有 14 项测试通过；MATLAB 侧新增回归尚未执行。
按 matlab-testing 技能先征求多信号导入、时间/数值保持和不清空已有运行的测试方案确认，
截至此记录仍未收到答复。没有把原生 SDI 打开或高级分析记为已验证通过。

当前真机验收入口见 [新机部署指南](../../../docs/NEW_MACHINE_DEPLOYMENT.md)。旧验证脚本已经退役，本阶段原始报告不覆盖当前 Qt APP 或重命名后的模型。

PyXCPHost.exe SHA-256：`cdeee62f670e6e3615b78012ac9df207ba6e6af4c623f3515f5e0555b6d6bd06`。

需求文档保持原样，SHA-256：`26a8c2df97ad62a27f0f10c01e6da1a2ba9e69d4acc0c54ebbf569188cf82b7d`。
