#!/usr/bin/env python3
"""Independent raw parser for fresh lab images (no attribute-list support)."""
import struct,sys
f=open(sys.argv[1],'rb')
def read(off,n):
 f.seek(off); b=f.read(n); assert len(b)==n; return b
def u(b,o,n): return int.from_bytes(b[o:o+n],'little')
b=read(0,512); sec=u(b,11,2);cs=sec*b[13];mft=u(b,48,8)*cs;s=int.from_bytes(b[64:65],'little',signed=True);rs=cs*s if s>0 else 1<<-s
# Fresh mkntfs lab's first nine MFT records are in its first contiguous extent.
def record(n):
 b=bytearray(read(mft+n*rs,rs));assert b[:4]==b'FILE'
 o=u(b,4,2);count=u(b,6,2);assert count==rs//sec+1
 for i in range(1,count):
  end=i*sec-2;assert b[end:end+2]==b[o:o+2];b[end:end+2]=b[o+2*i:o+2*i+2]
 return b
def attrs(n):
 b=record(n);o=u(b,20,2)
 while u(b,o,4)!=0xffffffff:
  length=u(b,o+4,4);assert length>=24
  yield b[o:o+length];o+=length
  assert o<rs

def runs(a):
 assert a[8];p=u(a,32,2);v=u(a,16,8);l=0;r=[]
 while a[p]:
  h=a[p];p+=1;nl=h&15;no=h>>4;assert nl
  length=u(a,p,nl);p+=nl
  if no: l+=int.from_bytes(a[p:p+no],'little',signed=True)
  p+=no;r.append((v,l if no else None,length));v+=length
 return r
bad=next(a for a in attrs(8) if u(a,0,4)==128 and a[u(a,10,2):u(a,10,2)+2*a[9]].decode('utf-16le')=='$Bad')
bm=next(a for a in attrs(6) if u(a,0,4)==128 and a[9]==0)
br=runs(bad);mr=runs(bm)
for arg in sys.argv[2:]:
 c=int(arg);v,l,n=next(r for r in br if r[0]<=c<r[0]+r[2]);assert l is not None and l+c-v==c
 byte=c//8;v,l,n=next(r for r in mr if r[0]*cs<=byte<(r[0]+r[2])*cs);assert l is not None
 bit=read(l*cs+byte-v*cs,1)[0]>>(c%8)&1;assert bit==1
 print(f'RAW PASS LCN={c}: BadClus identity mapping, Bitmap=1, MFT USA valid')
assert u(bad,40,8)==u(bad,48,8) and u(bad,56,8)==0 and u(bad,12,2)==0
print('RAW PASS BadClus size/flags convention preserved; runs=',br)
