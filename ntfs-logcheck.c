#include "ntfs-timespec-compat.h"
#include <stdlib.h>
#include <stdio.h>
#include <ntfs-3g/volume.h>
#include <ntfs-3g/inode.h>
#include <ntfs-3g/attrib.h>
#include <ntfs-3g/logfile.h>
int main(int argc,char **argv){
 if(argc!=2)return 2;
 ntfs_volume*v=ntfs_mount(argv[1],NTFS_MNT_RDONLY);if(!v)return 3;
 ntfs_inode*n=ntfs_inode_open(v,FILE_LogFile);if(!n)return 4;
 ntfs_attr*a=ntfs_attr_open(n,AT_DATA,AT_UNNAMED,0);if(!a)return 5;
 RESTART_PAGE_HEADER*r=NULL;int ok=ntfs_check_logfile(a,&r);int clean=ok?ntfs_is_logfile_clean(a,r):0;
 printf("logfile_structurally_valid=%d logfile_clean=%d\n",ok,clean);
 free(r);ntfs_attr_close(a);ntfs_inode_close(n);ntfs_umount(v,FALSE);return !(ok&&clean);
}
