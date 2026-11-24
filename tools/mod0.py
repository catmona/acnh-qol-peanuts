import sys,struct
img=open(sys.argv[1],'rb').read()
mod0=struct.unpack_from('<I',img,4)[0]
m=img[mod0:mod0+0x1c]; assert m[:4]==b'MOD0',m[:4]
dyn,bss_s,bss_e,eh_s,eh_e,modobj=[mod0+x for x in struct.unpack_from('<iiiiii',m,4)]
print('mod0',hex(mod0),'dyn',hex(dyn),'bss',hex(bss_s),hex(bss_e),'eh',hex(eh_s),hex(eh_e))
D={}
o=dyn
tags=[]
while True:
    t,v=struct.unpack_from('<qQ',img,o); o+=16
    if t==0: break
    tags.append((t,v)); D.setdefault(t,[]).append(v)
for t,v in tags: print(t,hex(v))
strtab=D[5][0]; symtab=D[6][0]; strsz=D[10][0]
# symbols: assume symtab ends at strtab
n=(strtab-symtab)//24
syms=[]
for i in range(n):
    nm,info,oth,shn,val,sz=struct.unpack_from('<IBBHQQ',img,symtab+i*24)
    s=img[strtab+nm:img.index(b'\0',strtab+nm)].decode()
    syms.append((val,sz,shn,info,s))
for s in syms:
    print(hex(s[0]),s[1],s[2],hex(s[3]),s[4])
