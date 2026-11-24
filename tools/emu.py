"""Run the QoL Core plugin's startup in an emulator against a main image and record what it does.

Usage: emu.py <plugin.bin> <main.bin> <romfs_dir> <out_prefix>

Records: every byte the plugin writes into main or its own code (through the svcMapProcessMemory alias),
every read it makes of main, every call into main, and its log output (svcOutputDebugString).
The plugin image is the decompressed NSO (nso.py); main.bin is a flat main image (unrewrite.py).
"""
import sys, struct, json, os, collections
from unicorn import *
from unicorn.arm64_const import *

PLUG, MAINF, ROMFS, OUT = sys.argv[1:5]
plug = bytearray(open(PLUG, 'rb').read())
main = open(MAINF, 'rb').read()

PAGE = 0x1000
up = lambda x: (x + PAGE - 1) & ~(PAGE - 1)

# ---- layout (contiguous like Horizon: rtld, main, subsdk0, subsdk6, sdk) ----
RTLD = 0x08000000
M = RTLD + 0x4000
MAIN_TEXT_END, MAIN_RO, MAIN_DATA = 0x3f07000, 0x3f07000, 0x4725000
MAIN_END = 0x5a06000
main = main[:MAIN_END].ljust(MAIN_END, b'\0')
SUB0 = M + MAIN_END
P = SUB0 + 0x4000
PLUG_TEXT_END, PLUG_RO, PLUG_DATA, PLUG_END = 0x94000, 0x94000, 0xad000, 0x215000
SDK = P + PLUG_END
STUBS = 0x7000000000
STACK = 0x7100000000; STACK_SIZE = 0x100000
TLS = 0x7200000000
HEAP = 0x7300000000; HEAP_SIZE = 0x1000000
DONE = 0x7400000000

uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
uc.ctl_set_cpu_model(UC_CPU_ARM64_MAX) if hasattr(uc, 'ctl_set_cpu_model') else None

regions = []  # (addr, size, type, perm) for svcQueryMemory
def region(addr, size, typ, perm, data=None):
    uc.mem_map(addr, size, UC_PROT_ALL)
    if data: uc.mem_write(addr, bytes(data[:size]))
    regions.append((addr, size, typ, perm))

def fake_module(base):
    # minimal module: text page (b +8, MOD0 offset), ro page, data page
    t = bytearray(PAGE)
    struct.pack_into('<II', t, 0, 0x14000002, 0x10)
    t[0x10:0x14] = b'MOD0'
    region(base, PAGE, 3, 5, t); region(base + PAGE, PAGE, 3, 1); region(base + 2 * PAGE, 2 * PAGE, 4, 3)

fake_module(RTLD)
region(M, MAIN_RO, 3, 5, main)
region(M + MAIN_RO, MAIN_DATA - MAIN_RO, 3, 1, main[MAIN_RO:])
region(M + MAIN_DATA, MAIN_END - MAIN_DATA, 4, 3, main[MAIN_DATA:])
fake_module(SUB0)

# ---- plugin: relocate ----
mod0 = struct.unpack_from('<I', plug, 4)[0]
dyn = mod0 + struct.unpack_from('<i', plug, mod0 + 4)[0]
D = collections.defaultdict(list); o = dyn
while True:
    t, v = struct.unpack_from('<qQ', plug, o); o += 16
    if t == 0: break
    D[t].append(v)
strtab, symtab = D[5][0], D[6][0]
def sym(i):
    nm, info, oth, shn, val, sz = struct.unpack_from('<IBBHQQ', plug, symtab + i * 24)
    return plug[strtab + nm:plug.index(b'\0', strtab + nm)].decode(), shn, val
imports = {}
def stub_for(name):
    if name not in imports: imports[name] = STUBS + 0x10 * len(imports)
    return imports[name]
def relocs(off, size):
    for o in range(off, off + size, 24):
        r_off, info, add = struct.unpack_from('<QQq', plug, o)
        typ, si = info & 0xffffffff, info >> 32
        if typ == 1027: v = P + add
        else:
            name, shn, val = sym(si)
            v = (P + val if shn else stub_for(name)) + add
        struct.pack_into('<Q', plug, r_off, v)
relocs(D[7][0], D[8][0])
relocs(D[23][0], D[2][0])
plug = plug.ljust(PLUG_END, b'\0')
region(P, PLUG_TEXT_END, 3, 5, plug)
region(P + PLUG_RO, PLUG_DATA - PLUG_RO, 3, 1, plug[PLUG_RO:])
region(P + PLUG_DATA, PLUG_END - PLUG_DATA, 4, 3, plug[PLUG_DATA:])
fake_module(SDK)
uc.mem_map(STUBS, 0x10000, UC_PROT_ALL)
uc.mem_write(STUBS, b'\xc0\x03\x5f\xd6' * 0x4000)  # ret
region(STACK, STACK_SIZE, 5, 3)
region(TLS, 0x4000, 5, 3)
region(HEAP, HEAP_SIZE, 5, 3)
uc.mem_map(DONE, PAGE, UC_PROT_ALL)
uc.reg_write(UC_ARM64_REG_TPIDRRO_EL0, TLS)
uc.reg_write(UC_ARM64_REG_CPACR_EL1, 0x300000)  # enable FP/SIMD

log = []; writes = {}; write_pcs = collections.Counter(); main_reads = collections.Counter(); main_calls = collections.Counter(); notes = []
def L(s):
    log.append(s); print(s, flush=True)

def rd(a, n): return bytes(uc.mem_read(a, n))
def cstr(a):
    b = b''
    while True:
        c = rd(a, 64); i = c.find(b'\0')
        if i >= 0: return (b + c[:i]).decode('utf-8', 'replace')
        b += c; a += 64
def X(i): return uc.reg_read(UC_ARM64_REG_X0 + i)
def setX(i, v): uc.reg_write(UC_ARM64_REG_X0 + i, v & 0xffffffffffffffff)
def ret(v=None):
    if v is not None: setX(0, v)
    uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

def where(a):
    if M <= a < M + MAIN_END: return f'main+{a - M:#x}'
    if P <= a < P + PLUG_END: return f'plug+{a - P:#x}'
    return f'{a:#x}'

# ---- aliases from svcMapProcessMemory ----
aliases = []  # (rw, ro, size, hook)
def on_alias_write(uc_, access, addr, size, value, ud):
    for rw, ro, sz, _ in aliases:
        if rw <= addr < rw + sz:
            tgt = ro + (addr - rw)
            vb = (value & ((1 << (8 * size)) - 1)).to_bytes(size, 'little')
            for k in range(size): writes[tgt + k] = vb[k]
            write_pcs[uc_.reg_read(UC_ARM64_REG_PC)] += 1
            uc_.mem_write(tgt, vb)
            return

# ---- fs ----
files = {}; dirs = {}; nexth = [1]
def hostpath(p):
    p = p.split(':', 1)[1] if ':' in p else p
    return os.path.join(ROMFS, p.lstrip('/'))
def fs_call(name):
    if 'OpenFileE' in name:
        p = cstr(X(1)); hp = hostpath(p)
        if os.path.isfile(hp):
            h = nexth[0]; nexth[0] += 1; files[h] = open(hp, 'rb').read()
            uc.mem_write(X(0), struct.pack('<Q', h)); L(f'# fs open {p} -> {h}'); return 0
        L(f'# fs open {p} -> not found'); return 0x202
    if 'GetFileSize' in name:
        uc.mem_write(X(0), struct.pack('<q', len(files[X(1)]))); return 0
    if 'ReadFileE' in name:
        h, off, buf, n = X(0), X(1), X(2), X(3); d = files[h][off:off + n]
        uc.mem_write(buf, d); return 0
    if 'CloseFile' in name: return 0
    if 'OpenDirectory' in name:
        p = cstr(X(1)); hp = hostpath(p)
        if os.path.isdir(hp):
            h = nexth[0]; nexth[0] += 1; dirs[h] = sorted(os.listdir(hp))
            dirs[h] = [(n, os.path.isfile(os.path.join(hp, n)), os.path.getsize(os.path.join(hp, n))) for n in dirs[h]]
            uc.mem_write(X(0), struct.pack('<Q', h)); L(f'# fs opendir {p} -> {len(dirs[h])} entries'); return 0
        L(f'# fs opendir {p} -> not found'); return 0x202
    if 'ReadDirectory' in name:
        outn, ent, h, cnt = X(0), X(1), X(2), X(3); lst = dirs[h]; take = lst[:cnt]; dirs[h] = lst[cnt:]
        for i, (n, isf, sz) in enumerate(take):
            e = bytearray(0x310); nb = n.encode()[:768]; e[:len(nb)] = nb; e[0x304] = 1 if isf else 0
            struct.pack_into('<q', e, 0x308, sz); uc.mem_write(ent + i * 0x310, bytes(e))
        uc.mem_write(outn, struct.pack('<q', len(take))); return 0
    if 'CloseDirectory' in name: return 0
    L(f'# unhandled import {name}'); return 0

# ---- svc ----
INFO = {2: 0x1000000000, 3: 0x1000000000, 4: HEAP, 5: HEAP_SIZE, 12: RTLD, 13: 0x7ff8000000,
        14: STACK, 15: 0x10000000, 18: 0x01006F8002326000, 6: 0xCD500000, 7: 0x7a00000, 20: 0}
threads = {}
def svc(num):
    if num == 0x27:
        s = rd(X(0), X(1)).decode('utf-8', 'replace').rstrip('\n'); L(s); setX(0, 0); return
    if num == 0x6:  # QueryMemory(MemoryInfo*, PageInfo*, addr) wrapper passes x0=meminfo x2=addr
        a = X(2); mi = X(0)
        if a >= 1 << 39:  # past the address space: Horizon reports one Inaccessible region to the top, so a walk wraps to 0 and ends
            uc.mem_write(mi, struct.pack('<QQIIIIII', 1 << 39, (1 << 64) - (1 << 39), 0x10, 0, 0, 0, 0, 0))
            setX(0, 0); setX(1, 0); return
        info = None; prev_end = 0
        for (b, s, t, p) in sorted(regions):
            if b <= a < b + s: info = (b, s, t, p); break
            if a < b: info = (prev_end, b - prev_end, 0, 0); break
            prev_end = b + s
        if info is None: info = (prev_end, (1 << 39) - prev_end, 0, 0)
        if info[2] == 0:  # free gap: find bounds
            lo = max([b + s for (b, s, t, p) in regions if b + s <= a] + [0])
            hi = min([b for (b, s, t, p) in regions if b > a] + [1 << 39])
            info = (lo, hi - lo, 0x10 if hi == 1 << 39 else 0, 0)
        uc.mem_write(mi, struct.pack('<QQIIIIII', info[0], info[1], info[2], 0, info[3], 0, 0, 0))
        setX(0, 0); setX(1, 0); return
    if num == 0x29:
        t, sub = X(1), X(3)
        v = INFO.get(t)
        if v is None: L(f'# GetInfo type {t} sub {sub:#x} -> unknown'); v = 0
        setX(0, 0); setX(1, v); return
    if num == 0x40: setX(0, 0); setX(1, 0x100); setX(2, 0x101); return
    if num == 0x8: threads[0x200] = (X(1), X(2)); setX(0, 0); setX(1, 0x200); return
    if num == 0x9:
        # run the receive thread's effect: exl stores the process handle at plug+0x2144e4
        uc.mem_write(P + 0x2144e4, struct.pack('<I', 0xFFFF8001)); setX(0, 0); return
    if num == 0x21: setX(0, 0); return
    if num == 0x18: setX(0, 0); setX(1, 0); return
    if num == 0x16: setX(0, 0); return
    if num == 0x1e: setX(0, len(log) * 1000); return
    if num == 0x74:
        rw, h, ro, size = X(0), X(1), X(2), X(3)
        uc.mem_map(rw, size, UC_PROT_ALL); uc.mem_write(rw, rd(ro, size))
        hk = uc.hook_add(UC_HOOK_MEM_WRITE, on_alias_write, begin=rw, end=rw + size - 1)
        aliases.append((rw, ro, size, hk)); setX(0, 0); return
    if num == 0x75:
        rw, h, ro, size = X(0), X(1), X(2), X(3)
        for i, al in enumerate(aliases):
            if al[0] == rw:
                uc.hook_del(al[3]); uc.mem_unmap(rw, size); aliases.pop(i); break
        setX(0, 0); return
    L(f'# svc {num:#x} x0={X(0):#x} x1={X(1):#x} -> 0'); setX(0, 0)

def on_intr(uc_, intno, ud):
    pc = uc_.reg_read(UC_ARM64_REG_PC)
    esr = uc_.reg_read(UC_ARM64_REG_ESR) if hasattr(sys.modules['unicorn.arm64_const'], 'UC_ARM64_REG_ESR') else None
    ins = struct.unpack('<I', rd(pc - 4, 4))[0]
    if ins & 0xffe0001f == 0xd4000001:
        svc((ins >> 5) & 0xffff); return
    L(f'# exception intno={intno} at {where(pc)} ins={ins:#x}'); uc_.emu_stop(); notes.append('exception')

imp_by_addr = {}
def on_code_stub(uc_, addr, size, ud):
    name = imp_by_addr.get(addr)
    if name is None: L(f'# call to unknown stub {addr:#x}'); ret(0); return
    ret(fs_call(name))

def on_main_exec(uc_, addr, size, ud):
    if M <= addr < M + MAIN_TEXT_END:
        lr = uc_.reg_read(UC_ARM64_REG_LR)
        main_calls[(addr - M, where(lr))] += 1
        ret(0)

def on_main_read(uc_, access, addr, size, value, ud):
    pc = uc_.reg_read(UC_ARM64_REG_PC)
    if P <= pc < P + PLUG_TEXT_END:
        main_reads[(addr - M, size, pc - P)] += 1

def on_done(uc_, addr, size, ud): uc_.emu_stop()

uc.hook_add(UC_HOOK_INTR, on_intr)
uc.hook_add(UC_HOOK_CODE, on_code_stub, begin=STUBS, end=STUBS + 0xffff)
uc.hook_add(UC_HOOK_CODE, on_main_exec, begin=M, end=M + MAIN_TEXT_END - 1)
uc.hook_add(UC_HOOK_MEM_READ, on_main_read, begin=M, end=M + MAIN_TEXT_END - 1)
uc.hook_add(UC_HOOK_CODE, on_done, begin=DONE, end=DONE + 3)
def on_unmapped(uc_, access, addr, size, value, ud):
    L(f'# unmapped access {access} at {addr:#x} size {size} pc={where(uc_.reg_read(UC_ARM64_REG_PC))}'); return False
uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)

# EMU_PROBE=off,off,...: print x0-x5, x19-x28 and lr each time the plugin reaches one of these offsets
def on_probe(uc_, addr, size, ud):
    regs = ' '.join(f'x{i}={X(i):#x}' for i in list(range(6)) + list(range(19, 29)))
    L(f'# probe {where(addr)} {regs} lr={where(uc_.reg_read(UC_ARM64_REG_LR))}')
for _o in filter(None, os.environ.get('EMU_PROBE', '').split(',')):
    _a = P + int(_o, 16); uc.hook_add(UC_HOOK_CODE, on_probe, begin=_a, end=_a)

def call(addr, *args, limit=int(os.environ.get("EMU_LIMIT", 200_000_000))):
    for i, a in enumerate(args): setX(i, a)
    uc.reg_write(UC_ARM64_REG_SP, STACK + STACK_SIZE - 0x100)
    uc.reg_write(UC_ARM64_REG_LR, DONE)
    try:
        uc.emu_start(addr, DONE, count=limit)
    except UcError as e:
        L(f'# emu error {e} at {where(uc.reg_read(UC_ARM64_REG_PC))} lr={where(uc.reg_read(UC_ARM64_REG_LR))}')
        notes.append(str(e))
    return X(0)

for n, a in imports.items(): imp_by_addr[a] = n

def dump(tag):
    mw = {a - M: v for a, v in writes.items() if M <= a < M + MAIN_END}
    pw = {a - P: v for a, v in writes.items() if P <= a < P + PLUG_END}
    def runs(d):
        out = [];
        for a in sorted(d):
            if out and out[-1][0] + len(out[-1][1]) == a: out[-1][1].append(d[a])
            else: out.append([a, bytearray([d[a]])])
        return [(hex(a), b.hex()) for a, b in out]
    rep = dict(tag=tag, layout=dict(main=hex(M), plugin=hex(P)), notes=notes,
               main_writes=runs(mw), plugin_writes=runs(pw),
               main_calls=[(hex(a), w, n) for (a, w), n in sorted(main_calls.items())],
               write_pcs=[(where(a), n) for a, n in sorted(write_pcs.items())],
               main_reads=[(hex(a), s, hex(pc), n) for (a, s, pc), n in sorted(main_reads.items())])
    json.dump(rep, open(f'{OUT}.{tag}.json', 'w'), indent=0)
    open(f'{OUT}.log', 'w', encoding='utf-8').write('\n'.join(log))
    print(f'## {tag}: main writes {len(mw)} bytes in {len(rep["main_writes"])} runs; plugin writes {len(pw)}; '
          f'main calls {len(main_calls)}; main read sites {len(main_reads)}')

if __name__ == '__main__':
    L(f'# imports: {list(imports)}')
    if os.environ.get('EMU_LOG', '0') == '1': uc.mem_write(P + 0xad00a, b'\x01')  # the plugin's own log switch; on, it breaks hook installs
    call(P + 0x6dbd0)
    dump('init')
    # the bootstrap hook (main+0x37b5464 -> plug+0x5a0) runs once the game has mounted its content: call it with an InlineCtx of zeros
    ctx = HEAP + HEAP_SIZE - 0x1000
    uc.mem_write(ctx, bytes(0x100))
    call(P + 0x5a0, ctx)
    dump('mount')
