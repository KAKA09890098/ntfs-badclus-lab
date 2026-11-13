/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef NTFS_TIMESPEC_COMPAT_H
#define NTFS_TIMESPEC_COMPAT_H

#include <time.h>

/* Debian's NTFS-3G header checks this guard, while glibc uses another one. */
#if defined(__GLIBC__) && !defined(__timespec_defined)
#define __timespec_defined 1
#endif

#endif
