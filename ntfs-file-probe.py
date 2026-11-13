#!/usr/bin/env python3
"""Create, map, and remove a temporary NTFS file on the configured test volume."""
import argparse
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import uuid

TARGET_TEXT = os.environ.get('BADCLUS_TARGET', '')
EXPECTED_SERIAL = os.environ.get('BADCLUS_EXPECTED_SERIAL', '')
RANGES = [(74045375, 74045648), (74060591, 74060864), (111341736, 111342000)]


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def identity():
    need(bool(TARGET_TEXT) and bool(EXPECTED_SERIAL),
         'set BADCLUS_TARGET and BADCLUS_EXPECTED_SERIAL')
    p = pathlib.Path(TARGET_TEXT).resolve(strict=True)
    s = pathlib.Path('/sys/class/block') / p.name
    need((s / 'partition').read_text().strip() == '2', 'target must be partition 2')
    parent = s.resolve().parent
    props = dict(x.split('=', 1) for x in subprocess.check_output(
        ['udevadm', 'info', '--query=property', '--name=/dev/' + parent.name],
        text=True).splitlines() if '=' in x)
    need(props.get('ID_SERIAL_SHORT') == EXPECTED_SERIAL, 'disk serial mismatch')
    need(int((s / 'start').read_text()) == 2097152 and
         int((s / 'size').read_text()) == 1951426560, 'partition geometry mismatch')
    mounts = pathlib.Path('/proc/self/mountinfo').read_text().splitlines()
    ids = []
    for ent in [parent] + list(parent.glob(parent.name + '*')):
        if not (ent / 'dev').exists():
            continue
        dev = (ent / 'dev').read_text().strip()
        ids.append(dev)
        need(all(line.split()[2] != dev for line in mounts), 'target is mounted')
        need(not list((ent / 'holders').iterdir()), 'target has active holders')
    rootline = next(x for x in mounts if ' / ' in x.split(' - ')[0])
    need(rootline.split()[2] not in ids, 'target is the Linux system disk')
    return p


def run(args, check=True):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
    if check and p.returncode:
        raise RuntimeError(f'{args[0]} exited {p.returncode}:\n{p.stdout}')
    return p


def mount(target, path, recover):
    identity()
    mode = 'recover' if recover else 'norecover'
    run(['ntfs-3g', '-o', f'{mode},uid=0,gid=0,umask=077', str(target), str(path)])
    src = run(['findmnt', '-n', '-o', 'SOURCE', '--target', str(path)]).stdout.strip()
    need(os.path.realpath(src) == str(target.resolve()),
         f'mount source mismatch: {src}')


def unmount(path):
    run(['sync', '-f', str(path)])
    run(['umount', str(path)])


def extents_for(target, inode):
    p = run(['ntfscluster', '-I', str(inode), str(target)])
    extents = []
    in_table = False
    for line in p.stdout.splitlines():
        if 'VCN' in line and 'LCN' in line and 'Length' in line:
            in_table = True
            continue
        if in_table:
            m = re.match(r'^\s*\d+\s+(-?\d+)\s+(\d+)\s*$', line)
            if m:
                lcn, length = map(int, m.groups())
                if lcn >= 0:
                    extents.append((lcn, lcn + length - 1, length))
    need(extents, 'no physical extents found for temporary file')
    return p.stdout, extents


def remove_if_same_inode(path, inode):
    if not path.exists():
        return False
    st = path.stat()
    need(inode is not None and st.st_ino == inode,
         'temporary path no longer identifies the file created by this probe')
    path.unlink()
    os.sync()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size-mib', type=int, default=1)
    ap.add_argument('--recover-unclean', action='store_true',
                    help='allow NTFS-3G to clear an unclean $LogFile during mount')
    args = ap.parse_args()
    need(os.geteuid() == 0, 'run with sudo')
    need(1 <= args.size_mib <= 16, 'size must be between 1 and 16 MiB')
    target = identity()
    probe = subprocess.run(['ntfs-3g.probe', '--readwrite', str(target)])
    recover = probe.returncode == 15 and args.recover_unclean
    need(probe.returncode == 0 or recover,
         f'write probe status {probe.returncode}; pass --recover-unclean only if log recovery is authorized')

    mountdir = pathlib.Path(tempfile.mkdtemp(prefix='ntfs-badclus-probe-', dir='/dev/shm'))
    file_path = mountdir / ('.ntfs-badclus-probe-' + uuid.uuid4().hex + '.bin')
    inode = None
    mounted = False
    created = False
    preserve_file = False
    try:
        mount(target, mountdir, recover)
        mounted = True
        with file_path.open('xb') as f:
            created = True
            inode = os.fstat(f.fileno()).st_ino
            block = bytes(1024 * 1024)
            for _ in range(args.size_mib):
                f.write(block)
            f.flush()
            os.fsync(f.fileno())
        os.sync()
        unmount(mountdir)
        mounted = False

        dump, extents = extents_for(target, inode)
        print(f'TEMP_FILE inode={inode} size_mib={args.size_mib}')
        print(dump, end='')
        for lo, hi, length in extents:
            print(f'ALLOCATED_LCN={lo}-{hi} length={length}')
            if any(not (hi < blo or lo > bhi) for blo, bhi in RANGES):
                preserve_file = True
                raise RuntimeError('temporary file overlaps a protected bad-cluster range; file retained for inspection')

        mount(target, mountdir, False)
        mounted = True
        st = file_path.stat()
        need(st.st_ino == inode and st.st_size == args.size_mib * 1024 * 1024,
             'temporary file identity changed; refusing to remove')
        file_path.unlink()
        created = False
        os.sync()
        unmount(mountdir)
        mounted = False

        deleted = run(['ntfscluster', '-I', str(inode), str(target)], check=False)
        need(f'Cannot open inode {inode}' in deleted.stdout,
             f'MFT record {inode} was not released after file deletion')
        print(f'TEST_FILE_DELETED inode={inode}')
        for lo, hi in RANGES:
            q = run(['ntfscluster', '-c', f'{lo}-{hi}', str(target)])
            need('/$BadClus/$DATA($Bad)' in q.stdout,
                 f'protected range {lo}-{hi} is not owned by $BadClus')
        check = run(['ntfsresize', '--info', '--bad-sectors', str(target)])
        print('NTFSRESIZE=PASS')
        print('\n'.join(x for x in check.stdout.splitlines()
                        if 'bad sector' in x or 'percent completed' in x))
        fix = run(['ntfsfix', '--no-action', str(target)])
        print('NTFSFIX_NO_ACTION=PASS')
        logcheck = pathlib.Path(__file__).with_name('ntfs-logcheck')
        print(run([str(logcheck), str(target)]).stdout, end='')
        print('FILE_ALLOCATION_PROBE=PASS')
    finally:
        if mounted:
            if created and not preserve_file:
                try:
                    remove_if_same_inode(file_path, inode)
                except Exception as e:
                    print(f'TEST_FILE_CLEANUP_REQUIRES_ATTENTION: {e}', file=sys.stderr)
            try:
                unmount(mountdir)
                mounted = False
            except Exception as e:
                print(f'UNMOUNT_REQUIRES_ATTENTION: {e}', file=sys.stderr)
        elif created and not preserve_file:
            try:
                pr = subprocess.run(['ntfs-3g.probe', '--readwrite', str(target)])
                need(pr.returncode == 0, 'volume is not clean enough for automatic test-file cleanup')
                mount(target, mountdir, False)
                mounted = True
                remove_if_same_inode(file_path, inode)
                unmount(mountdir)
                mounted = False
            except Exception as e:
                print(f'TEST_FILE_CLEANUP_REQUIRES_ATTENTION: {e}', file=sys.stderr)
        if not mounted:
            try:
                mountdir.rmdir()
            except OSError:
                pass


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('ABORTED:', e, file=sys.stderr)
        sys.exit(2)
