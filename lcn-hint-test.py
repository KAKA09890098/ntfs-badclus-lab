#!/usr/bin/env python3
"""Run the libntfs-3g allocator with each protected LCN as its start hint."""
import os, pathlib, subprocess, sys

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
    ids = []
    mounts = pathlib.Path('/proc/self/mountinfo').read_text().splitlines()
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


def main():
    need(os.geteuid() == 0, 'run with sudo')
    target = identity()
    probe = subprocess.run(['ntfs-3g.probe', '--readwrite', str(target)])
    need(probe.returncode == 0,
         f'read-write probe refused with status {probe.returncode}; no mount attempted')
    testbin = pathlib.Path(__file__).with_name('lcn-hint-test')
    result = subprocess.run([str(testbin), str(target)], text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, end='')
    need(result.returncode == 0, f'allocator test exited {result.returncode}')
    identity()
    print('ALLOCATOR_HINT_TEST=PASS')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('ABORTED:', e, file=sys.stderr)
        sys.exit(2)
