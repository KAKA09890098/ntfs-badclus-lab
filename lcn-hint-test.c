#include <time.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <ntfs-3g/volume.h>
#include <ntfs-3g/lcnalloc.h>
#include <ntfs-3g/runlist.h>
static const s64 bad[][2]={{74045375,74045648},{74060591,74060864},{111341736,111342000}};
static int bit(ntfs_volume *v,s64 c){u8 b=0;if(ntfs_attr_pread(v->lcnbmp_na,c/8,1,&b)!=1)return -1;return !!(b&(1<<(c%8)));}
int main(int argc,char **argv){
 if(argc!=2)return 2;
 ntfs_volume*v=ntfs_mount(argv[1],NTFS_MNT_EXCLUSIVE);if(!v){perror("ntfs_mount");return 3;}
 for(int i=0;i<3;i++){
  for(s64 c=bad[i][0];c<=bad[i][1];c++)if(bit(v,c)!=1){fprintf(stderr,"BADBIT_BEFORE region=%d lcn=%lld\n",i+4,(long long)c);return 4;}
  s64 expected=bad[i][1]+1;if(bit(v,expected)!=0){fprintf(stderr,"CANDIDATE_NOT_FREE region=%d lcn=%lld\n",i+4,(long long)expected);return 5;}
  runlist*rl=ntfs_cluster_alloc(v,0,1,bad[i][0],DATA_ZONE);if(!rl){perror("ntfs_cluster_alloc");return 6;}
  s64 got=rl[0].lcn;fprintf(stdout,"REGION=%02d HINT_LCN=%lld ALLOCATED_LCN=%lld LEN=%lld\n",i+4,(long long)bad[i][0],(long long)got,(long long)rl[0].length);fflush(stdout);
  int inside=0;for(int j=0;j<3;j++)if(got>=bad[j][0]&&got<=bad[j][1])inside=1;
  if(got<0||rl[0].length!=1||inside){fprintf(stderr,"UNSAFE_ALLOCATOR_RESULT region=%d lcn=%lld\n",i+4,(long long)got);free(rl);return 7;}
  if(bit(v,got)!=1){fprintf(stderr,"ALLOCATED_BIT_NOT_SET lcn=%lld\n",(long long)got);free(rl);return 8;}
  if(ntfs_cluster_free_from_rl(v,rl)){perror("ntfs_cluster_free_from_rl");free(rl);return 9;}
  free(rl);
  if(bit(v,got)!=0){fprintf(stderr,"FREED_BIT_NOT_CLEAR lcn=%lld\n",(long long)got);return 10;}
  for(s64 c=bad[i][0];c<=bad[i][1];c++)if(bit(v,c)!=1){fprintf(stderr,"BADBIT_AFTER region=%d lcn=%lld\n",i+4,(long long)c);return 11;}
  fprintf(stdout,"REGION=%02d PASS requested range skipped; transient allocation freed; marked bits preserved\n",i+4);fflush(stdout);
 }
 int rc=ntfs_umount(v,FALSE);if(rc){perror("ntfs_umount");return 12;}puts("UMOUNT_PASS");return 0;
}
