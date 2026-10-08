# SimRT 验证

R2024b 注册、库链接、代码生成与本地交叉编译的本轮结果见 [名称迁移验收](../../../tests/validation/simrt_migration_20261007/README.md)。

标准配置是 `SimRT` 硬件、`SimRT portable-linux-toolchain`、Linux x86-64、固定步长 1 ms、单任务和 UDP 5555。TCP 默认端口为 17725。

验证顺序：

1. `setupSimRTLinuxTarget` 注册，`verifySimRTEnvironment(Strict=true)` 检查本地环境。
2. `installSimRTARKLibrary` 安装统一库，检查 Serial、Digital IO、EtherCAT、CAN、TCP UDP 子库。
3. `buildSimRTLocal` 生成匹配的 ELF/A2L/manifest ZIP。
4. APP 校验 ZIP 与远端文件哈希，然后进行 XCP 观测和标定。

本地测试不证明硬件通信或长期周期稳定性。原始结果见 [验收索引](../../../tests/validation/README.md)；实际实时性边界见 [1 ms 方案](../../../docs/1ms_solution.md)。
