#!/usr/bin/env python3
"""Exercise the image-only editor against a disposable sparse NTFS volume."""
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
LCN = 30000
IMAGE_BYTES = 256 * 1024 * 1024


def run(args):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT).stdout


def main():
    for command in ("mkntfs", "ntfsresize"):
        if not pathlib.Path("/usr/bin", command).exists() and not pathlib.Path("/usr/sbin", command).exists():
            raise SystemExit(f"required test command not found: {command}")
    editor = ROOT / "badclus-lab"
    with tempfile.TemporaryDirectory(prefix="ntfs-badclus-image-test-") as td:
        image = pathlib.Path(td) / "volume.ntfs"
        with image.open("wb") as f:
            f.truncate(IMAGE_BYTES)
        run(["mkntfs", "-F", "-Q", "-L", "BADCLUS_LAB", str(image)])

        before = run([str(editor), "check", str(image), str(LCN)])
        if "bitmap=0" not in before or "mapped=-1" not in before:
            raise AssertionError(f"fresh target cluster was not free: {before}")

        added = run([str(editor), "add", str(image), str(LCN)])
        if "metadata written" not in added:
            raise AssertionError(f"image editor did not report an update: {added}")

        after = run([str(editor), "check", str(image), str(LCN)])
        if "bitmap=1" not in after or f"mapped={LCN}" not in after:
            raise AssertionError(f"image readback did not show the bad cluster: {after}")

        repeated = run([str(editor), "add", str(image), str(LCN)])
        if "already marked; unchanged" not in repeated:
            raise AssertionError(f"repeated add was not idempotent: {repeated}")

        verify = run([sys.executable, str(ROOT / "verify-lab.py"), str(image), str(LCN)])
        if f"RAW PASS LCN={LCN}" not in verify:
            raise AssertionError(f"independent raw parser failed: {verify}")

        resize = run(["ntfsresize", "--info", "--bad-sectors", str(image)])
        if "bad sector" not in resize.lower():
            raise AssertionError(f"ntfsresize did not report the registered cluster: {resize}")

    print("PASS: sparse NTFS image, add/check/idempotence, independent raw parser, ntfsresize")


if __name__ == "__main__":
    main()
