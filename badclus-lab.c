/* SPDX-License-Identifier: GPL-2.0-or-later
 * Experimental, single-cluster, regular-image-only NTFS metadata editor.
 * Always use a disposable copy. No journal transaction / crash recovery.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <time.h>
#include <limits.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/file.h>
#include <ntfs-3g/volume.h>
#include <ntfs-3g/attrib.h>
#include <ntfs-3g/inode.h>
#include <ntfs-3g/runlist.h>
#include <ntfs-3g/bitmap.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr,"REFUSED/FAILED line %d: %s (%s)\n",__LINE__,#x,strerror(errno)); exit(1); } } while(0)
static long long number(const char *s) { char *e; errno=0; long long v=strtoll(s,&e,10); REQUIRE(!errno && *s && !*e && v>=0); return v; }
int main(int argc,char **argv) {
 REQUIRE(argc==4 && (!strcmp(argv[1],"check") || !strcmp(argv[1],"add")));
 int write=!strcmp(argv[1],"add"); long long lcn=number(argv[3]);
 struct stat before; REQUIRE(!lstat(argv[2],&before) && S_ISREG(before.st_mode) && before.st_nlink==1);
 int fd=open(argv[2],(write?O_RDWR:O_RDONLY)|O_NOFOLLOW|O_EXCL); struct stat st;
 REQUIRE(fd>=0 && !fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_nlink==1 && st.st_dev==before.st_dev && st.st_ino==before.st_ino);
 REQUIRE(!flock(fd,LOCK_EX|LOCK_NB));
 /* /proc fd pins the checked file, preventing pathname substitution. */
 char path[64]; snprintf(path,sizeof(path),"/proc/self/fd/%d",fd);
 ntfs_volume *v=ntfs_mount(path,write?0:NTFS_MNT_RDONLY); REQUIRE(v);
 REQUIRE(!(v->flags & VOLUME_IS_DIRTY)); REQUIRE(lcn<v->nr_clusters);
 ntfschar name[]={cpu_to_le16('$'),cpu_to_le16('B'),cpu_to_le16('a'),cpu_to_le16('d')};
 ntfs_inode *ni=ntfs_inode_open(v,FILE_BadClus); REQUIRE(ni);
 ntfs_attr *na=ntfs_attr_open(ni,AT_DATA,name,4); REQUIRE(na && !ntfs_attr_map_whole_runlist(na));
 unsigned char bit; REQUIRE(ntfs_attr_pread(v->lcnbmp_na,lcn/8,1,&bit)==1);
 int i=0,n=0; while(na->rl[n].length) n++; while(i<n && lcn>=na->rl[i].vcn+na->rl[i].length) i++;
 REQUIRE(i<n); LCN mapped=na->rl[i].lcn<0?na->rl[i].lcn:na->rl[i].lcn+lcn-na->rl[i].vcn;
 printf("LCN=%lld cluster=%u sectors=%u bitmap=%d mapped=%lld runs=%d\n",lcn,v->cluster_size,v->sector_size,!!(bit&(1<<(lcn%8))),(long long)mapped,n);
 if(write) {
  if(mapped==lcn) { REQUIRE(bit&(1<<(lcn%8))); puts("already marked; unchanged"); }
  else {
   REQUIRE(mapped==LCN_HOLE && !(bit&(1<<(lcn%8))));
   REQUIRE(!NInoAttrList(ni) && ni->nr_extents==0);
   runlist_element *rl=calloc(n+3,sizeof(*rl)); REQUIRE(rl); int k=0;
   for(int j=0;j<n;j++) { if(j!=i) rl[k++]=na->rl[j]; else {
    s64 before=lcn-na->rl[j].vcn,after=na->rl[j].length-before-1;
    if(before) rl[k++]=(runlist_element){na->rl[j].vcn,LCN_HOLE,before};
    rl[k++]=(runlist_element){lcn,lcn,1};
    if(after) rl[k++]=(runlist_element){lcn+1,LCN_HOLE,after};
   }} rl[k]=na->rl[n];
   ntfs_attr_search_ctx *ctx=ntfs_attr_get_search_ctx(ni,NULL); REQUIRE(ctx);
   REQUIRE(!ntfs_attr_lookup(AT_DATA,name,4,CASE_SENSITIVE,0,NULL,0,ctx));
   ATTR_RECORD *a=ctx->attr; REQUIRE(a->non_resident && !sle64_to_cpu(a->lowest_vcn));
   int size=ntfs_get_size_for_mapping_pairs(v,rl,0,INT_MAX); REQUIRE(size>0);
   int off=le16_to_cpu(a->mapping_pairs_offset); REQUIRE(!ntfs_attr_record_resize(ni->mrec,a,(off+size+7)&~7));
   REQUIRE(!ntfs_mapping_pairs_build(v,(u8*)a+off,size,rl,0,NULL));
   /* Reserve first: interrupted update may leak a cluster, never double allocate. */
   REQUIRE(!ntfs_bitmap_set_bit(v->lcnbmp_na,lcn));
   REQUIRE(!ntfs_inode_sync(v->lcnbmp_na->ni)); REQUIRE(!fsync(fd));
   ntfs_inode_mark_dirty(ni); REQUIRE(!ntfs_inode_sync(ni)); REQUIRE(!fsync(fd));
   ntfs_attr_put_search_ctx(ctx); free(rl); puts("metadata written; reopen and verify required");
  }
 }
 ntfs_attr_close(na); REQUIRE(!ntfs_inode_close(ni)); REQUIRE(!ntfs_umount(v,FALSE)); REQUIRE(!close(fd)); return 0;
}
