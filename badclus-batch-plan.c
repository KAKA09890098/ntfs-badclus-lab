/* SPDX-License-Identifier: GPL-2.0-or-later
 * Read-only batch planner for three pre-authorized NTFS BadClus ranges.
 * Emits BCLBAT01: magic, MFT byte offset, bitmap-sector count, reserved,
 * old/new MFT record, then (sector byte offset, old/new sector) records.
 */
#define _GNU_SOURCE
#include "ntfs-timespec-compat.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <limits.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <ntfs-3g/volume.h>
#include <ntfs-3g/attrib.h>
#include <ntfs-3g/inode.h>
#include <ntfs-3g/runlist.h>
#include <ntfs-3g/mst.h>
#include <ntfs-3g/logfile.h>
#define R(x) do { if(!(x)) {fprintf(stderr,"REFUSED batch-plan line %d: %s\n",__LINE__,#x);exit(1);} }while(0)
#define SECTOR 512
#define MAX_BM 8
typedef struct { s64 byte; s64 physical; unsigned char old[SECTOR], now[SECTOR]; } bmrec;
static const s64 ranges[3][2]={{74045375,74045648},{74060591,74060864},{111341736,111342000}};
static s64 physical(ntfs_attr *a,s64 pos,s64 len) {
 R(!ntfs_attr_map_whole_runlist(a));
 for(runlist_element *r=a->rl;r->length;r++) {
  s64 begin=r->vcn*a->ni->vol->cluster_size,end=begin+r->length*a->ni->vol->cluster_size;
  if(pos>=begin && pos+len<=end) {R(r->lcn>=0);return r->lcn*a->ni->vol->cluster_size+pos-begin;}
 }
 R(0);return -1;
}
static int cmp_bm(const void *aa,const void *bb) {
 const bmrec *a=aa,*b=bb;return (a->byte>b->byte)-(a->byte<b->byte);
}
static bmrec *find_bm(bmrec *b,int n,s64 byte) {
 s64 base=byte&~((s64)SECTOR-1);
 for(int i=0;i<n;i++)if(b[i].byte==base)return &b[i];
 R(0);return NULL;
}
static void put32le(uint32_t x,unsigned char b[4]) { for(int i=0;i<4;i++)b[i]=(x>>(8*i))&255; }
static void put64le(uint64_t x,unsigned char b[8]) { for(int i=0;i<8;i++)b[i]=(x>>(8*i))&255; }
int main(int argc,char **argv) {
 R(argc==3 && !strcmp(argv[2],"--allow-dirty-log"));
 int fd=open(argv[1],O_RDONLY);R(fd>=0);
 ntfs_volume *v=ntfs_mount(argv[1],NTFS_MNT_RDONLY);R(v);
 R(v->cluster_size==4096 && v->sector_size==512 && v->mft_record_size==1024 && v->nr_clusters==243928319);
 R((le16_to_cpu(v->flags)&~0x0080)==0);
 R(!ntfs_volume_check_hiberfile(v,1));
 ntfs_inode *logni=ntfs_inode_open(v,FILE_LogFile);R(logni);
 ntfs_attr *log=ntfs_attr_open(logni,AT_DATA,AT_UNNAMED,0);R(log);
 RESTART_PAGE_HEADER *rp=NULL;BOOL log_ok=ntfs_check_logfile(log,&rp);R(log_ok);
 if (!NVolLogFileEmpty(v)) {
  RESTART_AREA *ra=(RESTART_AREA*)((u8*)rp+le16_to_cpu(rp->restart_area_offset));
  fprintf(stderr,"LOG_DIAG version=%d.%d current_lsn=%lld client_in_use=%u flags=0x%04x clean_flag=%d\n",(int)sle16_to_cpu(rp->major_ver),(int)sle16_to_cpu(rp->minor_ver),(long long)sle64_to_cpu(ra->current_lsn),(unsigned)le16_to_cpu(ra->client_in_use_list),(unsigned)le16_to_cpu(ra->flags),!!(ra->flags&RESTART_VOLUME_IS_CLEAN));
 }
 BOOL log_clean=ntfs_is_logfile_clean(log,rp);
 if (!log_clean) fprintf(stderr,"EXPERIMENT OVERRIDE: structurally valid but unclean $LogFile; read-only plan only.\n");
 free(rp);ntfs_attr_close(log);R(!ntfs_inode_close(logni));
 ntfs_inode *ni=ntfs_inode_open(v,FILE_BadClus);R(ni && !NInoAttrList(ni) && ni->nr_extents==0);
 ntfschar name[]={cpu_to_le16('$'),cpu_to_le16('B'),cpu_to_le16('a'),cpu_to_le16('d')};
 ntfs_attr *na=ntfs_attr_open(ni,AT_DATA,name,4);R(na && !ntfs_attr_map_whole_runlist(na));
 R(na->rl[0].vcn==0 && na->rl[0].lcn==LCN_HOLE && na->rl[0].length==74045376);
 R(na->rl[1].vcn==74045376 && na->rl[1].lcn==74045376 && na->rl[1].length==1);
 R(na->rl[2].vcn==74045377 && na->rl[2].lcn==LCN_HOLE && na->rl[2].length==v->nr_clusters-74045377 && !na->rl[3].length);
 ntfs_attr *bmp=v->lcnbmp_na;R(bmp && !ntfs_attr_map_whole_runlist(bmp));
 bmrec sectors[MAX_BM];int nb=0;
 for(int j=0;j<3;j++) {
  R(ranges[j][0]>=0 && ranges[j][1]>=ranges[j][0] && ranges[j][1]<v->nr_clusters);
  for(s64 c=ranges[j][0];c<=ranges[j][1];c++) {
   s64 byte=c/8,base=byte&~((s64)SECTOR-1);int found=0;
   for(int k=0;k<nb;k++)if(sectors[k].byte==base)found=1;
   if(!found){R(nb<MAX_BM);memset(&sectors[nb],0,sizeof(sectors[nb]));sectors[nb++].byte=base;}
  }
 }
 qsort(sectors,nb,sizeof(sectors[0]),cmp_bm);R(nb==3);
 for(int i=0;i<nb;i++) {
  sectors[i].physical=physical(bmp,sectors[i].byte,SECTOR);
  R(sectors[i].physical%SECTOR==0 && pread(fd,sectors[i].old,SECTOR,sectors[i].physical)==SECTOR);
  memcpy(sectors[i].now,sectors[i].old,SECTOR);
 }
 for(int j=0;j<3;j++)for(s64 c=ranges[j][0];c<=ranges[j][1];c++) {
  bmrec *q=find_bm(sectors,nb,c/8);int idx=(int)((c/8)-q->byte),mask=1<<(c%8);
  int was_bad=(c==74045376);int bit=!!(q->old[idx]&mask);
  R(bit==was_bad);
  q->now[idx]|=mask;
 }
 s64 mo=physical(v->mft_na,8*1024,1024);R(mo%SECTOR==0 && mo%4096<=3072);
 unsigned char oldm[1024];R(pread(fd,oldm,sizeof(oldm),mo)==sizeof(oldm));
 unsigned char decoded[1024];memcpy(decoded,oldm,sizeof(decoded));R(!ntfs_mst_post_read_fixup((NTFS_RECORD*)decoded,1024));R(!memcmp(decoded,ni->mrec,1024));
 ntfs_attr_search_ctx *ctx=ntfs_attr_get_search_ctx(ni,NULL);R(ctx);
 R(!ntfs_attr_lookup(AT_DATA,name,4,CASE_SENSITIVE,0,NULL,0,ctx));ATTR_RECORD *a=ctx->attr;
 R(a->non_resident && !a->flags && !a->lowest_vcn && !a->initialized_size);
 R(sle64_to_cpu(a->highest_vcn)==v->nr_clusters-1 && sle64_to_cpu(a->allocated_size)==v->nr_clusters*4096 && a->data_size==a->allocated_size);
 runlist_element rl[]={{0,LCN_HOLE,74045375},{74045375,74045375,274},{74045649,LCN_HOLE,14942},{74060591,74060591,274},{74060865,LCN_HOLE,37280871},{111341736,111341736,265},{111342001,LCN_HOLE,v->nr_clusters-111342001},{v->nr_clusters,LCN_ENOENT,0}};
 int bytes=ntfs_get_size_for_mapping_pairs(v,rl,0,INT_MAX),off=le16_to_cpu(a->mapping_pairs_offset);R(bytes>0 && off>=72 && off+bytes<=1024);
 R(!ntfs_attr_record_resize(ni->mrec,a,(off+bytes+7)&~7));
 R(!ntfs_mapping_pairs_build(v,(u8*)a+off,bytes,rl,0,NULL));
 unsigned char newm[1024];memcpy(newm,ni->mrec,1024);R(!ntfs_mst_pre_write_fixup((NTFS_RECORD*)newm,1024));
 unsigned char header[24]={0};memcpy(header,"BCLBAT01",8);put64le((uint64_t)mo,header+8);put32le((uint32_t)nb,header+16);put32le(log_clean?0:1,header+20);
 R(fwrite(header,1,sizeof(header),stdout)==sizeof(header));
 R(fwrite(oldm,1,1024,stdout)==1024 && fwrite(newm,1,1024,stdout)==1024);
 for(int i=0;i<nb;i++){unsigned char p[16];put64le((uint64_t)sectors[i].physical,p);put64le((uint64_t)sectors[i].byte,p+8);R(fwrite(p,1,16,stdout)==16 && fwrite(sectors[i].old,1,SECTOR,stdout)==SECTOR && fwrite(sectors[i].now,1,SECTOR,stdout)==SECTOR);}
 R(!fflush(stdout));
 fprintf(stderr,"PLAN_DIAG mft_offset=%lld bitmap_sectors=%d",(long long)mo,nb);
 for(int i=0;i<nb;i++)fprintf(stderr," bitmap[%d]=%lld",i,(long long)sectors[i].physical);
 fprintf(stderr,"\n");
 ntfs_attr_put_search_ctx(ctx);ntfs_attr_close(na);R(!ntfs_inode_close(ni));R(!ntfs_umount(v,FALSE));close(fd);return 0;
}
