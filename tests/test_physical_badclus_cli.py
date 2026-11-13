import importlib.util
import contextlib
import hashlib
import io
import os
import pathlib
import struct
import tempfile
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "physical-badclus-batch.py"
SPEC = importlib.util.spec_from_file_location("physical_badclus_batch", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def plan_with_log_flag(unclean=False):
    plan = bytearray(5192)
    plan[:8] = b"BCLBAT01"
    struct.pack_into("<I", plan, 16, 3)
    struct.pack_into("<I", plan, 20, int(unclean))
    return bytes(plan)


class CommitCommandTests(unittest.TestCase):
    def test_prepare_subcommand(self):
        args = MODULE.parse_args(["prepare"])
        self.assertEqual(args.mode, "prepare")

    def test_commit_accepts_documented_arguments(self):
        args = MODULE.parse_args(["commit", "/dev/shm/badclus-plan", "a" * 64])
        self.assertEqual(args.mode, "commit")
        self.assertEqual(args.backup_dir, pathlib.Path("/dev/shm/badclus-plan"))
        self.assertEqual(args.plan_sha256, "a" * 64)
        self.assertFalse(args.allow_unclean_log)

    def test_commit_accepts_unclean_log_flag_after_positionals(self):
        args = MODULE.parse_args([
            "commit", "/dev/shm/badclus-plan", "a" * 64,
            "--allow-unclean-log",
        ])
        self.assertTrue(args.allow_unclean_log)

    def test_commit_requires_both_positionals(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.parse_args(["commit", "/dev/shm/badclus-plan"])


class CommitPlanAuthorizationTests(unittest.TestCase):
    def test_clean_plan_needs_no_override(self):
        plan = plan_with_log_flag(False)
        digest = hashlib.sha256(plan).hexdigest()
        MODULE.validate_commit_request(plan, digest, digest, False)

    def test_unclean_plan_requires_explicit_override(self):
        plan = plan_with_log_flag(True)
        digest = hashlib.sha256(plan).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "unclean \\$LogFile"):
            MODULE.validate_commit_request(plan, digest, digest, False)
        MODULE.validate_commit_request(plan, digest, digest, True)

    def test_command_digest_must_match_manifest_and_plan(self):
        plan = plan_with_log_flag(False)
        digest = hashlib.sha256(plan).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "differs from manifest"):
            MODULE.validate_commit_request(plan, "0" * 64, digest, False)
        with self.assertRaisesRegex(RuntimeError, "differs from manifest"):
            MODULE.validate_commit_request(plan, digest, "0" * 64, False)

    def test_malformed_digest_is_rejected(self):
        plan = plan_with_log_flag(False)
        with self.assertRaisesRegex(RuntimeError, "invalid command-line"):
            MODULE.validate_commit_request(plan, "not-a-hash", "not-a-hash", False)


class MetadataRollbackTests(unittest.TestCase):
    def setUp(self):
        self.image = tempfile.TemporaryFile()
        self.image.truncate(8192)
        self.fd = self.image.fileno()
        self.mo = 0
        self.oldm = b"M" * 1024
        self.newm = b"N" * 1024
        self.sectors = [
            {"offset": 2048 + i * 512, "old": bytes([65 + i]) * 512,
             "new": bytes([97 + i]) * 512}
            for i in range(3)
        ]
        os.pwrite(self.fd, self.oldm, self.mo)
        for sector in self.sectors:
            os.pwrite(self.fd, sector["old"], sector["offset"])

    def tearDown(self):
        self.image.close()

    def assert_original_bytes(self):
        self.assertEqual(os.pread(self.fd, len(self.oldm), self.mo), self.oldm)
        for sector in self.sectors:
            self.assertEqual(os.pread(self.fd, 512, sector["offset"]), sector["old"])

    def verify_new_bytes(self):
        self.assertEqual(os.pread(self.fd, len(self.newm), self.mo), self.newm)
        for sector in self.sectors:
            self.assertEqual(os.pread(self.fd, 512, sector["offset"]), sector["new"])

    def test_sparse_file_commit_writes_bitmap_then_mft(self):
        MODULE.apply_metadata_transaction(
            self.fd, self.mo, self.oldm, self.newm, self.sectors,
            self.verify_new_bytes,
        )
        self.verify_new_bytes()

    def test_short_mft_write_restores_original_bytes(self):
        real_pwrite = os.pwrite
        failed = False

        def write_partial_mft_once(fd, data, offset):
            nonlocal failed
            if not failed and offset == self.mo and data == self.newm:
                failed = True
                return real_pwrite(fd, data[:128], offset)
            return real_pwrite(fd, data, offset)

        with mock.patch.object(MODULE.os, "pwrite", side_effect=write_partial_mft_once):
            with self.assertRaisesRegex(RuntimeError, "original MFT/Bitmap bytes were restored"):
                MODULE.apply_metadata_transaction(
                    self.fd, self.mo, self.oldm, self.newm, self.sectors,
                    self.verify_new_bytes,
                )
        self.assert_original_bytes()

    def test_verification_failure_restores_original_bytes(self):
        def fail_verification():
            raise RuntimeError("injected verification failure")

        with self.assertRaisesRegex(RuntimeError, "original MFT/Bitmap bytes were restored"):
            MODULE.apply_metadata_transaction(
                self.fd, self.mo, self.oldm, self.newm, self.sectors,
                fail_verification,
            )
        self.assert_original_bytes()


if __name__ == "__main__":
    unittest.main()
