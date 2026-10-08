# 模型构建入口

当前模型使用 `simrt_rt_single`，构建统一在 Windows MATLAB R2024b 中完成：

```matlab
addpath('D:/05SimRT/toolchain/simrt_linux_target');
setupSimRTLinuxTarget;
result = buildSimRTLocal("D:/05SimRT/demos/Demo_XCP_Qt/models/simrt_rt_single/simrt_rt_single.slx", ...
    Address="192.168.193.195");
disp(result.archive);
```

使用同一轮生成的 ZIP 进行 SSH 部署。完整流程与验收边界见 [工具链](../TOOLCHAIN.md)；阶段原始结果见 [验收索引](../../tests/validation/README.md)。
