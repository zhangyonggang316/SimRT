# 工程存档

当前工程统一使用 SimRT 名称。源码、MATLAB 注册、功能库、模型、APP 和使用说明在同一版本中发布。

唯一构建路线是 Windows MATLAB R2024b 生成代码、portable-linux-toolchain 本地交叉编译、导出配套 ELF/A2L/manifest，再通过 SSH 部署到 ARK2120。完整操作见 [工具链](TOOLCHAIN.md)。

## 保存与恢复

`tests/maintenance/save_version.py` 将完整工程保存到工程外，逐文件记录 SHA-256，并再次读取 ZIP 校验。已存在的版本目录不会被静默覆盖。

2026-10-07 的名称迁移和构建路线整理会同步到版本存档，位置与校验结果见 [迁移记录](../tests/validation/simrt_migration_20261007/README.md)。迁移前的生成代码和部署产物独立保存在 `D:/05SimRT_versions/pre_migration_20261007/`，仅用于回退。

恢复时先校验归档，再按 [新机部署](NEW_MACHINE_DEPLOYMENT.md) 注册 MATLAB 库。运行 APP 必须保留整个 `demos/Demo_XCP_Qt`，生成模型必须保留完整工具链及 sysroot。

## 学习与证据

新生成的 C、构建回调、运行时及说明都随工程保留，阅读入口为 [架构说明](ARCHITECTURE.md)。历史验收的原始日志、JSON 和哈希记录表示当时事实，不能通过改名当作本版本的新验收。
