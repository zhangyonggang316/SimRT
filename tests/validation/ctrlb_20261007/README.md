# R2024b Hardware 页 Ctrl+B 修复

## 问题与修复

`simrt_rt_single` 已设置 `GenCodeOnly=off` 和本地工具链，但 Hardware 页的构建按钮被禁用。R2024b 从目标参数的 `Build options` 分组读取构建动作；原注册将地址和构建动作混放在 `Local build` 分组，返回的构建动作列表为空，工具栏进入 `HWBoardDeployDisabledContext`。

现将地址保留在 `Local build`，将 `Build action` 放到 `Build options` 首项，启用该参数且仅提供 `Build`。刷新目标注册、重新打开已保存模型后，工具栏进入 `HWBoardBuildSelectedBuildContext`，实际 `buildHardwareBoardAction2` 的 `enabled` 为 `true`。

进一步执行工具栏动作发现，R2024b 普通 Build 会临时关闭 `ExtMode`，导致 XCP 头文件和代码生成依赖缺失。新增 `onCodeGenEntry` 注册回调，在代码生成开始前恢复 `ExtMode=on`，保留模型的 Dirty 状态。代码生成之后的构建回调太晚，此时参数已锁定，因此不在后期回调中更改它。

## 实际验证

- `tSimRTLinuxTarget` 共 11 项测试全部通过，包括新增的构建动作识别、工具栏上下文和 XCP 入口配置回归。
- 通过当前 MATLAB R2024b 桌面会话的工具栏 ActionService 执行 `buildHardwareBoardAction2`，完整构建成功，约 64 秒。
- 产物：`demos/Demo_XCP_Qt/models/simrt_rt_single/simrt_rt_single_local/20261007_011239_986.zip`。
- ZIP SHA-256：`db43679432acc894ca91cf4fd256ffae4b08d637bf7917ef63134343b7892228`。
- ZIP 包含配套 ELF、A2L 和 manifest；构建回执记录 `success=true`、`remote_operations_performed=false`。
- 未连接或改动实时机，未改变 APP 当前选择的模型包；本报告不代表新产物已经通过实时机验收。
- 原生桌面自动化通道不可用，未发送物理 Ctrl+B 按键；验证的是 Hardware 页按钮自身的动作、启用状态和完整构建结果。

`hardware_diagnostics.log` 保留排查阶段的失败及最后一次成功构建；最终回执见 `build_report.json`，工具栏状态见 `hardware_action.json`。本地目标回归由 `runRegression.m` 执行，详细结果写入 `target_tests.json` 和 `target_tests.log`。

## 复验

在工程注册已更新、主模型已保存且停止的 R2024b 桌面中：

```matlab
addpath('D:/05SimRT/toolchain/simrt_linux_target');
setupSimRTLinuxTarget;
addpath('D:/05SimRT/tests/validation/ctrlb_20261007');
refreshBuildUI; % 仅重新打开未修改、已停止的主模型
buildFromHardwareTab; % 实际执行工具栏动作，并校验新回执和 ZIP
runRegression;
```

`slbuild` 能成功不能单独证明工具栏入口可用；回归同时检查可用构建动作和工具栏上下文，实际构建还必须产生新的成功回执。
