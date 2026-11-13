# NTFS BadClus 实验工具 v0.1.1

## 使用场景

这套工具针对一种具体的数据恢复场景：读取扫描或 `ddrescue` 日志已经给出 NTFS 分区内难读区域的物理 LBA，恢复人员希望 NTFS 在以后分配普通文件空间时绕开这些簇。

本项目就是从一次真实的 Linux/Windows 处理问题整理出来的：Windows 下尝试用 NtfsMarkBad 登记坏簇时，写入 `$MFT` 返回 `STATUS_ACCESS_DENIED`。随后改在 Linux 上研究 NTFS-3G/libntfs-3g，检查目标分区、把物理 LBA 换算成卷内 LCN，并直接维护 NTFS 的 `$BadClus:$Bad` 与 `$Bitmap`。这个实验工具把该过程做成可核对的计划、受控提交和分配验证。

## 它解决什么问题

- 将已确认的卷内不可读簇登记为 NTFS 坏簇，让遵循 `$BadClus` 的文件系统分配器不再把这些簇分配给普通文件。
- 同步更新 `$BadClus:$Bad` 的映射和 `$Bitmap` 分配位，避免只改一个元数据而留下互相矛盾的状态。
- 在写入前核验设备身份和计划，在写入后回读 MFT/Bitmap，并检查 NTFS-3G 的分配器和真实临时文件是否避开保护区。

它解决的是 NTFS 卷内的文件系统分配问题，不是硬盘介质修复。标记不会修复、重映射或清除物理坏扇区；也不能拦截直接写块设备、其他文件系统或不遵循该 NTFS 元数据的软件。已在本次 NTFS-3G/Linux 配置上测试，不能据此保证所有 Windows/Linux 驱动和所有应用的行为。

## 结合本次实际案例

恢复扫描给出了六段难读物理 LBA。前三段在 R: 卷之前，位于分区外，不能记入 R: 的 `$BadClus`；04～06 三段位于卷内，才是本工具处理的目标。卷起始 LBA 为 2097152，扇区 512 字节，簇 4096 字节，即每簇 8 个 LBA。每段前后各扩一簇作为缓冲。

| 区域 | 原始物理 LBA | 加缓冲后物理 LBA | 加缓冲后 LCN | 簇数 |
|---|---:|---:|---:|---:|
| 04 | 594460160–594462335 | 594460152–594462343 | 74045375–74045648 | 274 |
| 05 | 594581888–594584063 | 594581880–594584071 | 74060591–74060864 | 274 |
| 06 | 892831048–892833151 | 892831040–892833159 | 111341736–111342000 | 265 |

本次 `$BadClus:$Bad` 最终覆盖 813 个簇；其中 812 个是本批次新增，04 区有 1 个簇此前已经标记。提交后原始 MFT USA、坏簇 runlist 和全部 Bitmap 位回读通过。

验证分配时，NTFS-3G 创建的 1 MiB 临时文件实际落在 LCN 31277464–31277719，随后删除，没有与上述保护范围重叠。对三个保护区起始 LCN 进行分配提示时，libntfs-3g 也都分配到了区外。

## 适用边界

- 这是针对上述 WD10EZEX 测试卷几何和 04～06 区域制作的实验版本；设备序列号由运行时提供，卷和分区几何不匹配时程序应拒绝。不要直接拿它处理其他客户盘或其他分区。
- 仅在目标盘已完成必要镜像/备份、明确允许承担实验写入风险时使用。真实盘提交会写 `$Bitmap` 扇区和 MFT 记录 8。
- 如果坏区位于分区外、无法确认设备身份、目标簇已有未知文件占用，或 `$LogFile` 状态不满足程序条件，就应停止并重新诊断。
- `$BadClus` 标记不能取代镜像、文件恢复或硬盘更换；磁盘仍可能继续恶化。该程序不运行 `chkdsk` 修复，也不运行 `ntfsfix` 修复。

本版能力对比见 [CHANGELOG.md](CHANGELOG.md)，逐项测试记录见 [RESULTS.md](RESULTS.md)。

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

源码发行包为 `dist/ntfs-badclus-lab-v0.1.1.tar.gz`，旁边有 Git bundle 和 SHA-256 文件。详细内容在 [RELEASE_NOTES.md](RELEASE_NOTES.md)。

GitHub 发布工作流位于 `.github/workflows/publish-release.yml`。创建名称为 `release-v$(cat VERSION)` 的分支会触发发布；若首次运行失败，向该分支推送修正提交会重试。工作流核对分支名、版本和归档文件，然后创建 `v$(cat VERSION)` tag/Release，并上传源码包、Git bundle 和 SHA-256 清单。创建该分支就是发布操作；发布前应先核对 `VERSION`、发行说明和归档。工作流只接受 `release-v` 开头且与 `VERSION` 一致的分支，已存在的 Release 不会被覆盖。

## 许可证

GPL-2.0-or-later，见 [LICENSE](LICENSE)。
