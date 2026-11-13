#!/usr/bin/env python3
import os,sys,stat,struct,subprocess,json,hashlib,datetime,pathlib,shutil
from pathlib import Path
TARGET_TEXT=os.environ.get('BADCLUS_TARGET','')
TARGET=Path(TARGET_TEXT) if TARGET_TEXT else None
SERIAL=os.environ.get('BADCLUS_EXPECTED_SERIAL','')
PLAN='/dev/shm/badclus-batch.plan'
PLANNER=str(Path(__file__).with_name('badclus-batch-plan'))
RANGES=[(74045375,74045648),(74060591,74060864),(111341736,111342000)]
ORIGINAL=[(74045376,74045647),(74060592,74060863),(111341737,111341999)]
LBAS=[(594460152,594462343),(594581880,594584071),(892831040,892833159)]

def need(ok,msg):
    if not ok: raise RuntimeError(msg)
def identity():
    need(TARGET is not None and bool(SERIAL),'set BADCLUS_TARGET and BADCLUS_EXPECTED_SERIAL')
    p=TARGET.resolve(strict=True)
    need(str(p).startswith('/dev/'),'target path mismatch')
    s=pathlib.Path('/sys/class/block')/p.name
    need((s/'partition').read_text().strip()=='2','not partition 2')
    parent=s.resolve().parent
    props=dict(x.split('=',1) for x in subprocess.check_output(['udevadm','info','--query=property','--name=/dev/'+parent.name],text=True).splitlines() if '=' in x)
    need(props.get('ID_SERIAL_SHORT')==SERIAL,'target serial mismatch')
    need(int((s/'start').read_text())==2097152 and int((s/'size').read_text())==1951426560,'target partition geometry mismatch')
    # Verify that neither the disk nor its partitions are mounted or held.
    ids=[]
    for ent in [parent]+list(parent.glob(parent.name+'*')):
        if not (ent/'dev').exists(): continue
        dev=(ent/'dev').read_text().strip(); ids.append(dev)
        need(all(line.split()[2]!=dev for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines()),'target disk/partition is mounted')
        need(not list((ent/'holders').iterdir()),'target disk/partition has active holders')
    rootline=next(x for x in pathlib.Path('/proc/self/mountinfo').read_text().splitlines() if ' / ' in x.split(' - ')[0])
    rootdev=rootline.split()[2]
    need(rootdev not in ids,'target is the Linux system disk')
    return p,s,parent,ids

def open_device(mode):
    p,s,parent,ids=identity()
    flags=(os.O_RDONLY if mode=='ro' else os.O_RDWR)|os.O_EXCL|os.O_NOFOLLOW
    fd=os.open(str(p),flags)
    st=os.fstat(fd)
    dev=(s/'dev').read_text().strip().split(':')
    need(stat.S_ISBLK(st.st_mode) and (os.major(st.st_rdev),os.minor(st.st_rdev))==tuple(map(int,dev)),'opened device identity mismatch')
    return fd

def make_plan(fd):
    p=subprocess.run([PLANNER,f'/proc/self/fd/{fd}','--allow-dirty-log'],pass_fds=(fd,),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    sys.stderr.write(p.stderr.decode(errors='replace'))
    need(p.returncode==0,'read-only batch planner refused; no write made')
    need(len(p.stdout)==5192 and p.stdout[:8]==b'BCLBAT01','bad batch plan size/format')
    return p.stdout

def decode_plan(b):
    need(len(b)==5192 and b[:8]==b'BCLBAT01','invalid plan')
    mo=struct.unpack_from('<Q',b,8)[0];n=struct.unpack_from('<I',b,16)[0]
    flags=struct.unpack_from('<I',b,20)[0]
    need(n==3 and flags in (0,1),'unexpected bitmap sector count/plan flags')
    oldm=b[24:1048];newm=b[1048:2072];sectors=[];q=2072
    for i in range(n):
        off,byte=struct.unpack_from('<QQ',b,q);old=b[q+16:q+528];new=b[q+528:q+1040]
        need(len(old)==512 and len(new)==512 and off%512==0 and byte%512==0,'invalid bitmap sector record')
        sectors.append({'offset':off,'byte':byte,'old':old,'new':new})
        q+=1040
    need(q==len(b),'trailing plan bytes')
    need([x['byte'] for x in sectors]==[9255424,9257472,13917696],'bitmap logical offsets changed')
    need([x['offset'] for x in sectors]==[3199982080,3199984128,3204644352],'bitmap physical offsets changed')
    return mo,oldm,newm,sectors

def plan_log_unclean(plan):
    return bool(struct.unpack_from('<I',plan,20)[0] & 1)

def u(b,o,n): return int.from_bytes(b[o:o+n],'little')
def parse_record(raw):
    need(len(raw)==1024 and raw[:4]==b'FILE','invalid MFT signature')
    usa=u(raw,4,2);cnt=u(raw,6,2);need(cnt==3 and usa+cnt*2<=1024,'invalid MFT USA')
    m=bytearray(raw)
    for i in range(1,cnt):
        end=i*512-2;need(m[end:end+2]==m[usa:usa+2],'MFT USA mismatch');m[end:end+2]=m[usa+i*2:usa+i*2+2]
    attrs=[];off=u(m,20,2)
    while off+8<=1024 and u(m,off,4)!=0xffffffff:
        length=u(m,off+4,4);need(length>=24 and off+length<=1024,'MFT attribute bounds error')
        attrs.append(m[off:off+length]);off+=length
    need(off+4<=1024 and u(m,off,4)==0xffffffff,'MFT end marker missing')
    return m,attrs

def attr_name(a):
    n=a[9];off=u(a,10,2)
    return bytes(a[off:off+n*2]).decode('utf-16le') if n else ''
def get_runs(a):
    need(a[8]==1,'BadClus $Bad stream is not nonresident')
    p=u(a,32,2);v=u(a,16,8);last_lcn=0;runs=[]
    while p<len(a) and a[p]:
        h=a[p];p+=1;nl=h&15;no=h>>4;need(nl>0 and p+nl+no<=len(a),'invalid mapping pair')
        length=u(a,p,nl);p+=nl;need(length>0,'zero length mapping pair')
        if no:
            delta=int.from_bytes(a[p:p+no],'little',signed=True);last_lcn+=delta;lcn=last_lcn
            p+=no
        else: lcn=None
        runs.append((v,lcn,length));v+=length
    need(p<len(a) and a[p]==0,'mapping pair terminator missing')
    return runs

def verify(fd,plan,phase):
    mo,oldm,newm,sectors=decode_plan(plan)
    rawm=os.pread(fd,1024,mo)
    need(rawm==newm,'MFT readback differs from planned record')
    m,attrs=parse_record(rawm)
    bad=[a for a in attrs if u(a,0,4)==0x80 and attr_name(a)=='$Bad']
    need(len(bad)==1,'$BadClus:$Bad attribute missing or duplicated')
    a=bad[0]
    need(u(a,12,2)==0 and u(a,56,8)==0,'$BadClus flags/initialized size changed')
    need(u(a,24,8)==243928318 and u(a,40,8)==u(a,48,8)==243928319*4096,'$BadClus VCN/sizes changed')
    expected=[(0,None,74045375),(74045375,74045375,274),(74045649,None,14942),(74060591,74060591,274),(74060865,None,37280871),(111341736,111341736,265),(111342001,None,132586318)]
    runs=get_runs(a);need(runs==expected,f'unexpected final $BadClus mapping pairs: {runs}')
    bits=0
    for s in sectors:
        rb=os.pread(fd,512,s['offset']);need(rb==s['new'],f'Bitmap sector readback mismatch at {s["offset"]}')
        need(sum((x^y).bit_count() for x,y in zip(s['old'],s['new']))==[273,274,265][sectors.index(s)],'unexpected Bitmap change count')
    for lo,hi in RANGES:
        for c in range(lo,hi+1):
            base=(c//8)&~511
            s=next(x for x in sectors if x['byte']==base)
            byte=(c//8)-base;need((s['new'][byte]>>(c%8))&1,'target Bitmap bit is clear')
            bits+=1
    need(bits==813,'target cluster count mismatch')
    print(f'{phase}: RAW PASS; MFT USA valid; 3 $BadClus identity runs; 813/813 Bitmap bits=1; changed bitmap bits=812')
    print('FINAL_RUNS='+json.dumps(runs,separators=(',',':')))

def run_check(program,fd,args):
    q=subprocess.run([program,*args,f'/proc/self/fd/{fd}'],pass_fds=(fd,),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    return q.returncode,q.stdout

def save(out,name,data):
    p=out/name
    with open(p,'xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.chmod(p,0o600)

def main():
    need(os.geteuid()==0,'sudo -n required')
    need(subprocess.check_output(['findmnt','-no','FSTYPE','/dev/shm'],text=True).strip()=='tmpfs','temporary backup path is not RAM tmpfs')
    mode=sys.argv[1] if len(sys.argv)>1 else 'prepare'
    if mode=='prepare':
        identity();fd=open_device('ro')
        try:
            plan=make_plan(fd);mo,oldm,newm,sectors=decode_plan(plan)
            need(os.pread(fd,1024,mo)==oldm,'MFT changed during planning')
            for s in sectors:need(os.pread(fd,512,s['offset'])==s['old'],'Bitmap changed during planning')
            rc,report=run_check('ntfsresize',fd,['--info','--bad-sectors']);need(rc==0,'pre-write ntfsresize consistency check failed:\n'+report)
            pfx=subprocess.run(['ntfsfix','--no-action',f'/proc/self/fd/{fd}'],pass_fds=(fd,),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            need(pfx.returncode==0,'pre-write ntfsfix read-only check failed:\n'+pfx.stdout)
        finally:os.close(fd)
        out=pathlib.Path('/dev/shm')/('wd10-badclus-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        out.mkdir(mode=0o700)
        save(out,'batch-plan.bin',plan);save(out,'ntfsresize-before.txt',report.encode());save(out,'ntfsfix-before.txt',pfx.stdout.encode())
        manifest={'target':str(TARGET),'resolved':str(TARGET.resolve()),'serial':SERIAL,'partition_start_lba':2097152,'cluster_bytes':4096,'sector_bytes':512,'buffer_clusters_each_side':1,'ignored_outside_volume_lbas':[[53248,55423],[55424,59647],[59648,67967]],'regions':[{'id':'04','original_lba':[594460160,594462335],'original_lcn':[74045376,74045647],'buffered_lba':list(LBAS[0]),'buffered_lcn':list(RANGES[0]),'clusters':274,'already_bad_clusters':1,'new_clusters':273},{'id':'05','original_lba':[594581888,594584063],'original_lcn':[74060592,74060863],'buffered_lba':list(LBAS[1]),'buffered_lcn':list(RANGES[1]),'clusters':274,'already_bad_clusters':0,'new_clusters':274},{'id':'06','original_lba':[892831048,892833151],'original_lcn':[111341737,111341999],'buffered_lba':list(LBAS[2]),'buffered_lcn':list(RANGES[2]),'clusters':265,'already_bad_clusters':0,'new_clusters':265}],'total_clusters':813,'new_bad_clusters':812,'mft_record_offset':mo,'bitmap_sectors':[{'partition_byte_offset':x['offset'],'bitmap_byte_base':x['byte'],'new_bits':n} for x,n in zip(sectors,[273,274,265])],'plan_sha256':hashlib.sha256(plan).hexdigest(),'logfile_unclean':plan_log_unclean(plan),'precheck_ntfsresize':report,'precheck_ntfsfix':pfx.stdout}
        save(out,'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode())
        print(json.dumps(manifest,ensure_ascii=False,indent=2));print('RAM_BACKUP_DIR='+str(out));print('PREPARE_ONLY: target disk was not written.')
        cmd=f"sudo BADCLUS_TARGET=... BADCLUS_EXPECTED_SERIAL=... python3 -B '{Path(__file__).name}' commit '{out}' {manifest['plan_sha256']}"
        if plan_log_unclean(plan):cmd+=' --allow-unclean-log'
        print('REVIEWED COMMIT COMMAND: '+cmd)
    elif mode=='commit':
        need(len(sys.argv)==3,'commit requires RAM backup directory')
        out=pathlib.Path(sys.argv[2]);need(out.parent==pathlib.Path('/dev/shm') and out.is_dir() and not out.is_symlink(),'backup directory must remain on /dev/shm')
        outst=out.stat();need(outst.st_uid==0 and stat.S_IMODE(outst.st_mode)==0o700,'backup ownership/mode mismatch')
        manifest=json.loads((out/'manifest.json').read_text());plan=(out/'batch-plan.bin').read_bytes()
        need(hashlib.sha256(plan).hexdigest()==manifest['plan_sha256'],'plan digest mismatch')
        need(not plan_log_unclean(plan) or a.allow_unclean_log,
             'plan records an unclean $LogFile; re-run commit with --allow-unclean-log after review')
        identity();fd=open_device('ro')
        try:
            need(make_plan(fd)==plan,'fresh read-only plan differs; refusing to write')
            mo,oldm,newm,sectors=decode_plan(plan)
            need(os.pread(fd,1024,mo)==oldm,'MFT preimage differs')
            for s in sectors:need(os.pread(fd,512,s['offset'])==s['old'],'Bitmap preimage differs')
            save(out,'mft-record.before.bin',oldm)
            for i,s in enumerate(sectors):save(out,f'bitmap-sector-{i}.before.bin',s['old'])
        finally:os.close(fd)
        identity();fd=open_device('rw')
        try:
            need(os.pread(fd,1024,mo)==oldm,'MFT changed after exclusive open')
            for s in sectors:need(os.pread(fd,512,s['offset'])==s['old'],'Bitmap changed after exclusive open')
            # Reserve clusters first; write and read back each sector before the MFT update.
            for i,s in enumerate(sectors):
                need(os.pwrite(fd,s['new'],s['offset'])==512,f'short Bitmap write for sector {i}; RAM backup retained')
                os.fsync(fd);need(os.pread(fd,512,s['offset'])==s['new'],f'Bitmap readback failed for sector {i}; RAM backup retained')
            need(os.pwrite(fd,newm,mo)==1024,'short MFT record write; RAM backup retained')
            os.fsync(fd);verify(fd,plan,'COMMIT_READBACK')
        finally:os.close(fd)
        identity();fd=open_device('ro')
        try:
            verify(fd,plan,'INDEPENDENT_REOPEN')
            rc,post=run_check('ntfsresize',fd,['--info','--bad-sectors'])
            (out/'ntfsresize-after.txt').write_text(post);need(rc==0,'post-write ntfsresize check failed; metadata writes and RAM backups retained:\n'+post)
            pfx=subprocess.run(['ntfsfix','--no-action',f'/proc/self/fd/{fd}'],pass_fds=(fd,),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            (out/'ntfsfix-after.txt').write_text(pfx.stdout);need(pfx.returncode==0,'post-write ntfsfix read-only check failed; metadata writes retained:\n'+pfx.stdout)
        finally:os.close(fd)
        disk='/dev/'+identity()[2].name
        smart=subprocess.run(['smartctl','-x','-d','sat',disk],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (out/'smart-after.txt').write_text(smart.stdout)
        manifest['completed_at_local']=datetime.datetime.now().astimezone().isoformat();manifest['metadata_writes']='3 x 512-byte $Bitmap sectors, then 1 x 1024-byte MFT record 8';manifest['post_ntfsresize_rc']=rc;manifest['post_ntfsresize']=post;manifest['post_ntfsfix_rc']=pfx.returncode;manifest['post_ntfsfix']=pfx.stdout;manifest['smart_rc']=smart.returncode;manifest['commit_result']='completed and verified';
        save(out,'final-report.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode())
        print('COMPLETED: target metadata written and independently verified.')
        print('RAM_BACKUP_DIR='+str(out));print('NTFSRESIZE_AFTER_BEGIN');print(post);print('NTFSFIX_AFTER_BEGIN');print(pfx.stdout);print('SMART_SUMMARY');
        for line in smart.stdout.splitlines():
            if any(k in line for k in ['SMART overall-health','Current_Pending_Sector','Offline_Uncorrectable','Reallocated_Sector_Ct','Temperature_Celsius','SMART Error Log','Error ']):print(line)
        print('REPORT_SHA256='+hashlib.sha256((out/'final-report.json').read_bytes()).hexdigest())
    else:raise RuntimeError('mode must be prepare or commit')
if __name__=='__main__':
    try:main()
    except Exception as e:print('ABORTED:',e,file=sys.stderr);sys.exit(2)
