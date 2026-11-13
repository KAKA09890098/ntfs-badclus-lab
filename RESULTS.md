# Recorded experiment result

- `$BadClus:$Bad` contains three identity-mapped intervals: LCN 74045375–74045648, 74060591–74060864, and 111341736–111342000.
- `$Bitmap` marks all 813 buffered clusters allocated; 812 bits were newly set.
- The raw MFT USA and runlist checks passed after commit, file create/delete, and allocator-hint tests.
- `ntfsresize --info --bad-sectors` completed with exit status 0 and reported at least 813 bad sectors.
- `ntfsfix --no-action` completed with exit status 0.
- The NTFS-3G allocator was called with start hints 74045375, 74060591, and 111341736. It returned free LCNs 31277464, 31281560, and 31285656, respectively; each transient bit was then cleared and the bad-cluster bits remained set.
- A 1 MiB file created through NTFS-3G occupied LCNs 31277464–31277719, then was deleted. No file data was written into the protected ranges.
- Initial write mounting used NTFS-3G recovery because `$LogFile` was unclean. After normal unmount, the log checker reported the journal structurally valid and clean.
- SMART overall-health reported `PASSED`, while `Current_Pending_Sector` remained 833 and the ATA error log contained UNC entries. The drive is still a failing test device; no whole-disk surface scan was run.

These results describe the tested NTFS-3G/Linux setup and do not claim that the physical drive has been repaired.
