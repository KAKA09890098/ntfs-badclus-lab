CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror
NTFS_CPPFLAGS ?= -I/usr/include
NTFS_LDLIBS ?= -l:libntfs-3g.so.89

.PHONY: all clean check-python
all: badclus-batch-plan lcn-hint-test ntfs-logcheck badclus-lab

badclus-batch-plan: badclus-batch-plan.c
	$(CC) $(CFLAGS) $(NTFS_CPPFLAGS) $< $(NTFS_LDLIBS) -o $@

lcn-hint-test: lcn-hint-test.c
	$(CC) $(CFLAGS) $(NTFS_CPPFLAGS) $< $(NTFS_LDLIBS) -o $@

ntfs-logcheck: ntfs-logcheck.c
	$(CC) $(CFLAGS) $(NTFS_CPPFLAGS) $< $(NTFS_LDLIBS) -o $@

badclus-lab: badclus-lab.c
	$(CC) $(CFLAGS) $(NTFS_CPPFLAGS) $< $(NTFS_LDLIBS) -o $@

check-python:
	python3 -B -m py_compile physical-badclus-batch.py lcn-hint-test.py ntfs-file-probe.py verify-lab.py

clean:
	rm -f badclus-batch-plan lcn-hint-test ntfs-logcheck badclus-lab
	rm -rf __pycache__
