# NTFS BadClus 实验工具 v0.1.1

本次是文档修订版。README 现在按实际数据恢复场景解释工具用途：从难读扇区 LBA 定位到 NTFS 卷内 LCN，维护 `$BadClus:$Bad` 和 `$Bitmap`，并验证普通文件分配是否避开保护区。

README 也记录了本案例中 Windows NtfsMarkBad 写 `$MFT` 返回 `STATUS_ACCESS_DENIED`、Linux NTFS-3G 实验处理、六段 LBA 中卷内外范围的区别，以及本次文件分配验证结果和工具边界。

本版只修订说明文档，程序逻辑未变。硬盘实验结果沿用 `RESULTS.md` 中记录的数据；没有因为文档更新再次写入测试盘。

程序仍绑定案例几何与 LCN 区间，具有实验性质。真实盘操作仅限核实后的可牺牲测试盘。目标盘序列号通过运行时环境变量提供，不写入发行源码。

完整差异见 `CHANGELOG.md`；使用场景、适用边界和运行条件见 `README.md`。
