CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror
NTFS_PKG_CONFIG ?= $(shell if pkg-config --exists ntfs-3g 2>/dev/null; then echo ntfs-3g; elif pkg-config --exists libntfs-3g 2>/dev/null; then echo libntfs-3g; fi)
NTFS_CPPFLAGS ?= $(shell if [ -n "$(NTFS_PKG_CONFIG)" ]; then pkg-config --cflags $(NTFS_PKG_CONFIG); else echo -I/usr/include; fi)
NTFS_LDLIBS ?= $(shell if [ -n "$(NTFS_PKG_CONFIG)" ]; then pkg-config --libs $(NTFS_PKG_CONFIG); else lib=$$(ldconfig -p 2>/dev/null | awk '/libntfs-3g[.]so[.][0-9]+/ {print $$1; exit}'); if [ -n "$$lib" ]; then printf '%s' "-Wl,-l:$$lib"; else printf '%s' '-lntfs-3g'; fi; fi)

.PHONY: all clean check check-python check-image
all: badclus-batch-plan lcn-hint-test ntfs-logcheck badclus-lab

check: all check-python check-image

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
	python3 -B -m unittest discover -s tests -p 'test_*.py' -v

check-image: badclus-lab
	python3 -B tests/test_sparse_ntfs_image.py

clean:
	rm -f badclus-batch-plan lcn-hint-test ntfs-logcheck badclus-lab
	rm -rf __pycache__
