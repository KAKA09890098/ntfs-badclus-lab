# 版本变更说明

## v0.1.1 — 使用场景与问题说明

- 重写 README 开头，说明工具用于把已确认的 NTFS 卷内难读 LBA 通过 `$BadClus:$Bad` 和 `$Bitmap` 标记为坏簇，让 NTFS 分配器绕开这些簇。
- 补充本项目的实际起因：Windows NtfsMarkBad 尝试写 `$MFT` 时返回 `STATUS_ACCESS_DENIED`，随后在 Linux 上研究 NTFS-3G/libntfs-3g 的受控元数据方案。
- 补充六段扫描区域中卷外与卷内区域的区别、04～06 实际范围、单簇缓冲、写后元数据检查及文件分配测试结果。
- 明确坏簇标记只影响遵循 NTFS 元数据的文件分配，不修复物理介质、不恢复不可读数据，也不拦截原始块设备写入。
- 这是文档修订版，程序逻辑未变；物理盘实验报告仍见 `RESULTS.md`。

## v0.1.0 — 首个打包实验版

### 原有能力

- `badclus-lab.c` 面向普通稀疏镜像文件，禁止把设备节点作为输入；验证单个 LCN 的 `$BadClus:$Bad` 与 `$Bitmap` 变化。
- `verify-lab.py` 直接解析镜像的 MFT USA、mapping pairs 和 `$Bitmap`，作为独立校验器。
- 早期 `physical-badclus.py` 为单簇真实盘实验提供设备身份检查、只读 prepare、计划摘要和受控提交。

### 本次改动

1. **三段批量范围**：把区域 04、05、06 一次转换为 3 个 identity-mapped `$BadClus` run；01～03 按卷外处理规则跳过。
2. **保护缓冲**：每段两侧各加一个 4096 字节簇（8 个逻辑 LBA）。最终共 813 簇，其中 812 个新增，1 个此前已标记。
3. **Bitmap 一致性**：先验证每个目标簇的旧 `$BadClus` 映射与 `$Bitmap` 位相符；只允许 free 位升级为 allocated，未知已分配位会中止。合并并重建 runlist，保持 `$BadClus` 属性大小与标志。
4. **两阶段提交**：prepare 使用只读设备句柄，写出二进制计划、SHA-256、写前元数据和只读一致性结果；commit 重新核对设备、计划摘要及前像，再按 Bitmap → MFT 顺序写入、同步、回读。
5. **设备保护**：固定核验目标分区号、序列号（运行时提供）、分区起点和大小；拒绝系统盘、已挂载设备及 holders；写入句柄使用独占打开。
6. **写后校验**：独立解析 MFT USA、`$BadClus` mapping pairs、卷大小/属性约定及所有目标 Bitmap 位；再运行 `ntfsresize --info --bad-sectors` 和 `ntfsfix --no-action`。
7. **日志状态透明**：只读计划记录 `$LogFile` clean 状态；未清洁计划需要 `--allow-unclean-log` 才能提交。提交程序不清日志、不执行修复。
8. **分配行为测试**：新增 libntfs-3g allocator hint 测试；对已标记 LCN 发起一个簇的分配提示，确认实际选择在保护区外，释放临时位并确认保护位仍为 1。
9. **文件级验证**：新增 NTFS-3G 临时文件探针，可创建文件、离线读取实际物理 runlist、确认不与保护区相交、删除文件并检查 `$BadClus` 所有权。对未清洁日志默认拒绝；恢复日志必须显式加参数。
10. **发行与报告**：加入 Makefile、版本号、中文 README/变更说明、实验结果、版本发布说明、源码归档和 SHA-256 清单。
11. **GitHub Release 发布流程**：新增受限 Actions 工作流；创建与 `VERSION` 一致的 `release-v*` 分支后，自动核对发行文件、创建版本 tag/Release，并上传源码包、Git bundle 和校验清单。

### 本次验证记录

- `$BadClus` 三段 runlist 和 813 个 Bitmap 位经提交后、文件创建/删除后、allocator hint 测试后均通过原始回读。
- `ntfsresize`、`ntfsfix --no-action`、日志检查均通过。
- 小文件 1 MiB 实际分配到 LCN 31277464–31277719，随后删除。
- allocator 对提示 LCN 74045375、74060591、111341736 分别返回 31277464、31281560、31285656；各临时分配已释放。
- 这些结果只验证 NTFS 元数据及 NTFS-3G/Linux 分配行为，不代表物理硬盘修复或 SMART 介质健康。
