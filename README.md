# NTFS BadClus 实验工具 v0.1.0

这是一个针对已核验 WD10EZEX 测试卷的 Linux / NTFS-3G 实验工具集。它把原有的单簇 `$BadClus` 实验扩展为三段批量登记、单簇缓冲保护、事务计划与提交、原始元数据复核，以及 NTFS 分配器和临时文件验证。

> **实验性质**：仅用于可牺牲的测试盘。代码固定了本案例的 NTFS 几何和 04～06 LCN 范围；任何不匹配都会拒绝。它不是通用 NTFS 修复程序，也不做硬盘固件重映射。

## 本案例范围

物理扇区为 512 字节，NTFS 簇为 4096 字节（每簇 8 个 LBA）。每个处理区间向前、向后各扩展 1 个簇。

| 区域 | 原物理 LBA | 加缓冲后的物理 LBA | 加缓冲后的 LCN | 簇数 |
|---|---:|---:|---:|---:|
| 04 | 594460160–594462335 | 594460152–594462343 | 74045375–74045648 | 274 |
| 05 | 594581888–594584063 | 594581880–594584071 | 74060591–74060864 | 274 |
| 06 | 892831048–892833151 | 892831040–892833159 | 111341736–111342000 | 265 |

01～03 位于卷外，按案例规则跳过。04 区的 LCN 74045376 在本批处理前已登记。最终 `$BadClus:$Bad` 包含 813 个簇，批次新增 812 个。

## 原有与新增能力

**原型已有能力**：针对稀疏 NTFS 测试镜像检查 `$BadClus:$Bad`、`$Bitmap` 和 MFT USA；以单个 LCN 生成和检查映射；在普通镜像文件上验证 runlist/bitmap 变更。

**v0.1.0 新增或扩展**：

- 一次计划 04～06 三段连续范围，并自动将每段扩展 1 个簇。
- 按现存 `$BadClus` runlist 与 `$Bitmap` 位逐簇核对；只允许空闲簇或已正确登记的坏簇，发现未知占用就拒绝。
- 生成只读二进制计划；提交前校验计划 SHA-256、设备身份、分区边界、挂载/holder 状态和原始 MFT/Bitmap 前像。
- 先写并回读 `$Bitmap` 扇区，再写并回读 MFT 记录 8；独立解析 USA、属性、mapping pairs 和 Bitmap。
- 备份、计划和报告放在 `/dev/shm`，不把实验备份写到系统盘。
- 对未清洁 `$LogFile` 的计划作显式标记；提交该计划必须带 `--allow-unclean-log`。这不会清空日志。
- 用 libntfs-3g 的 `ntfs_cluster_alloc()` 在每段坏 LCN 上设置搜索提示，记录实际分配位置并释放临时分配。
- 可选创建、映射、删除一个小型 NTFS 临时文件；默认拒绝未清洁卷。只有明确加 `--recover-unclean` 才会允许 NTFS-3G 清理日志。
- `ntfsresize --info --bad-sectors`、`ntfsfix --no-action`、SMART 和 `$LogFile` 状态检查。

详细逐项对照见 [CHANGELOG.md](CHANGELOG.md)，测试结果见 [RESULTS.md](RESULTS.md)。

## 构建

```sh
sudo apt install build-essential ntfs-3g ntfs-3g-dev
make
make check-python
```

如系统头文件或库位于非标准路径，可覆盖 `NTFS_CPPFLAGS` 和 `NTFS_LDLIBS`。仓库不包含编译产物或 NTFS-3G 的二进制依赖。

## 运行前配置

硬盘序列号不保存在仓库中。先用只读方式重新确认设备，再设置环境变量：

```sh
export BADCLUS_TARGET=/dev/disk/by-id/<已核实的分区2路径>
export BADCLUS_EXPECTED_SERIAL=<已核实的硬盘序列号>
```

程序还会核对固定的分区号、起点和大小；拒绝已挂载设备、活动 holder 及 Linux 系统盘。不要只凭 `/dev/sdX` 名称运行。

## 只读准备与提交

先生成只读计划：

```sh
sudo BADCLUS_TARGET="$BADCLUS_TARGET" BADCLUS_EXPECTED_SERIAL="$BADCLUS_EXPECTED_SERIAL" python3 -B physical-badclus-batch.py prepare
```

检查 JSON、`RAM_BACKUP_DIR`、三个范围和 `plan_sha256`。再使用生成的目录和摘要提交：

```sh
sudo BADCLUS_TARGET="$BADCLUS_TARGET" BADCLUS_EXPECTED_SERIAL="$BADCLUS_EXPECTED_SERIAL" python3 -B physical-badclus-batch.py commit /dev/shm/<计划目录> <plan_sha256>
```

若计划记录 `$LogFile` 未清洁，程序会拒绝普通提交；只有在审阅并明确接受该状态后才加 `--allow-unclean-log`。提交仅写计划内的 `$Bitmap` 扇区和 MFT 记录 8，不执行格式化、`chkdsk` 或 `ntfsfix` 修复。任一步回读不符会中止并保留 `/dev/shm` 备份。

## 分配器与文件测试

分配提示测试调用真实 libntfs-3g 分配器，但不创建文件数据；临时设置一个其他空闲簇的 Bitmap 位后立刻释放，并验证坏簇位未变：

```sh
sudo BADCLUS_TARGET="$BADCLUS_TARGET" BADCLUS_EXPECTED_SERIAL="$BADCLUS_EXPECTED_SERIAL" python3 -B lcn-hint-test.py
```

文件测试会在卷上写入一个临时文件，卸载后读取实际 runlist，再挂载删除并复核坏簇。默认只接受 clean 日志：

```sh
sudo BADCLUS_TARGET="$BADCLUS_TARGET" BADCLUS_EXPECTED_SERIAL="$BADCLUS_EXPECTED_SERIAL" python3 -B ntfs-file-probe.py
```

只有用户明确同意日志恢复时才传 `--recover-unclean`。NTFS-3G 的该选项会清空 `$LogFile`，可能造成一致性问题。测试文件和事务备份使用 RAM 临时目录，重启后消失。

## 发行版

源码发行包为 `dist/ntfs-badclus-lab-v0.1.0.tar.gz`，旁边有 Git bundle 和 SHA-256 文件。详细内容在 [RELEASE_NOTES.md](RELEASE_NOTES.md)。

GitHub 发布工作流位于 `.github/workflows/publish-release.yml`。创建名称为 `release-v$(cat VERSION)` 的分支会触发发布；若首次运行失败，向该分支推送修正提交会重试。工作流核对分支名、版本和归档文件，然后创建 `v$(cat VERSION)` tag/Release，并上传源码包、Git bundle 和 SHA-256 清单。创建该分支就是发布操作；发布前应先核对 `VERSION`、发行说明和归档。工作流只接受 `release-v` 开头且与 `VERSION` 一致的分支，已存在的 Release 不会被覆盖。

## 许可证

GPL-2.0-or-later，见 [LICENSE](LICENSE)。
