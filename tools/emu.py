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
PAGE = 0x1000
up = lambda x: (x + PAGE - 1) & ~(PAGE - 1)
if open(PLUG, 'rb').read(4) == b'NSO0':   # an NSO: its segments and bss give the module's real size, as the console's loader takes it
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import nso
    _info, plug = nso.load(PLUG); _s = _info['segs']
    PLUG_TEXT_END, PLUG_RO, PLUG_DATA = up(_s[0]['size']), _s[1]['moff'], _s[2]['moff']
    PLUG_END = up(_s[2]['moff'] + _s[2]['size'] + _info['bss'])
else:   # a flat image of QoL Core 1.1.0's subsdk6
    plug = bytearray(open(PLUG, 'rb').read())
    PLUG_TEXT_END, PLUG_RO, PLUG_DATA, PLUG_END = 0x94000, 0x94000, 0xad000, 0x215000
if open(MAINF, 'rb').read(4) == b'NSO0':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import nso
    main = bytes(nso.load(MAINF)[1])
else: main = open(MAINF, 'rb').read()

# EMU_PEANUTS=<out/build/layout.json> (with the built subsdk6 and EMU_IPS=<main IPS32>): the host as Peanuts lays it out. No rtld; each module followed by a patch
# area, so the modules stand farther apart than on the console and the far branches are re-aimed as the loader does (xmod); QueryMemory gives 4 KiB free pages
# outside the modules; svcMapProcessMemory and the process-handle svcs are placeholders; the alias region is real and svcMapPhysicalMemory maps in it
PEANUTS = json.load(open(os.environ['EMU_PEANUTS'])) if os.environ.get('EMU_PEANUTS') else None
GAP = 0x40000 if PEANUTS else 0
PATCH_AREA = 0x10000

# ---- layout (contiguous like Horizon: rtld, main, subsdk0, subsdk6, sdk; sizes of ACNH 3.0.3's own NSOs, segments and bss on a page) ----
RTLD_SIZE, SUB0_SIZE = 0x6000, 0x66c000
RTLD = 0x08000000
M = RTLD if PEANUTS else RTLD + RTLD_SIZE
MAIN_TEXT_END, MAIN_RO, MAIN_DATA = 0x3f07000, 0x3f07000, 0x4725000
MAIN_END = 0x5a06000
main = bytearray(main[:MAIN_END].ljust(MAIN_END, b'\0'))
MAIN_CLEAN_TEXT = bytes(main[:MAIN_TEXT_END])   # before any IPS
SUB0 = M + MAIN_END + GAP
P = SUB0 + SUB0_SIZE + GAP
SDK = P + PLUG_END + GAP
CONSOLE_P = MAIN_END + SUB0_SIZE   # subsdk6 from main on the console

def b_target(w, o):
    d = w & 0x3FFFFFF; return o + 4 * (d - ((d & 0x2000000) << 1))
def b_word(w, frm, to):
    assert abs(to - frm) < 1 << 27 and not (to - frm) & 3
    return (w & 0xFC000000) | (((to - frm) >> 2) & 0x3FFFFFF)
if PEANUTS:
    # the mod's IPS32 into main (offsets count the NSO header), then each far b in main (the sites) aimed at the plugin's host base
    # EMU_IPS unset: main stays unpatched (the discovery run: every check passes, so every plugin read of main's text shows up in main_text_reads)
    ips = open(os.environ['EMU_IPS'], 'rb').read() if os.environ.get('EMU_IPS') else b'IPS32EEOF'; assert ips[:5] == b'IPS32'; o = 5; ips_sites = []
    while ips[o:o + 4] != b'EEOF':
        off, n = struct.unpack_from('>IH', ips, o); o += 6
        main[off - 0x100:off - 0x100 + n] = ips[o:o + n]; o += n; ips_sites.append(off - 0x100)
    for s in ips_sites:
        w = struct.unpack_from('<I', main, s)[0]; t = b_target(w, s); assert CONSOLE_P <= t < CONSOLE_P + PLUG_TEXT_END
        struct.pack_into('<I', main, s, b_word(w, M + s, P + t - CONSOLE_P))
    # EMU_LAZY=1 (the discovery run): main's text stays as the dump has it and each site gets its IPS word only when the plugin installs that site's hook, which
    # is what the window shows the plugin on Peanuts; so the plugin's checks pass and every plugin read of main's text shows up in main_text_reads
    lazy = {s: bytes(main[s:s + 4]) for s in ips_sites} if os.environ.get('EMU_LAZY') else {}
    for s in lazy: main[s:s + 4] = MAIN_CLEAN_TEXT[s:s + 4]
    # the plugin's far b / bl, at the console's distance from main, aimed at main's host base
    n_far = 0
    for o in range(0, PLUG_TEXT_END, 4):
        w = struct.unpack_from('<I', plug, o)[0]
        if w & 0x7C000000 != 0x14000000: continue
        t = b_target(w, o)
        if 0 <= t < PLUG_END: continue
        tm = CONSOLE_P + t; assert 0 <= tm < MAIN_TEXT_END, hex(o)
        struct.pack_into('<I', plug, o, b_word(w, P + o, M + tm)); n_far += 1
    print(f'# peanuts layout: main {M:#x}, plugin {P:#x} (main+{P - M:#x}, console main+{CONSOLE_P:#x}); {len(ips_sites)} IPS sites, {n_far} far branches re-aimed', flush=True)
STUBS = 0x7000000000
STACK = 0x7100000000; STACK_SIZE = 0x100000
TLS = 0x7200000000
HEAP = 0x7300000000; HEAP_SIZE = 0x1000000
DONE = 0x7400000000

# ---- relocate main and the plugin at their bases (R_RELATIVE: base + addend; symbols: own definitions, else a stub that returns 0) ----
imports = {}
def stub_for(name):
    if name not in imports: imports[name] = STUBS + 0x10 * len(imports)
    return imports[name]
def relocate(img, base):
    mod0 = struct.unpack_from('<I', img, 4)[0]
    dyn = mod0 + struct.unpack_from('<i', img, mod0 + 4)[0]
    D = collections.defaultdict(list); o = dyn
    while True:
        t, v = struct.unpack_from('<qQ', img, o); o += 16
        if t == 0: break
        D[t].append(v)
    strtab, symtab = D[5][0], D[6][0]
    def sym(i):
        nm, info, oth, shn, val, sz = struct.unpack_from('<IBBHQQ', img, symtab + i * 24)
        return img[strtab + nm:img.index(b'\0', strtab + nm)].decode(), shn, val
    def rela(off, size):
        for o in range(off, off + size, 24):
            r_off, info, add = struct.unpack_from('<QQq', img, o)
            typ, si = info & 0xffffffff, info >> 32
            if typ == 1027: v = base + add
            else:
                name, shn, val = sym(si)
                v = (base + val if shn else stub_for(name)) + (0 if typ == 1026 else add)
            struct.pack_into('<Q', img, r_off, v & 0xffffffffffffffff)
    if D[7]: rela(D[7][0], D[8][0])
    if D[23]: rela(D[23][0], D[2][0])
    if D[36]:   # DT_RELR
        where_ = None
        for (v,) in struct.iter_unpack('<Q', bytes(img[D[36][0]:D[36][0] + (D[35][0] & ~7)])):
            if not v & 1: slots = [v]; where_ = v + 8
            else: slots = [where_ + 8 * b for b in range(63) if v >> (b + 1) & 1]; where_ += 63 * 8
            for s_ in slots: struct.pack_into('<Q', img, s_, (struct.unpack_from('<Q', img, s_)[0] + base) & 0xffffffffffffffff)
uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
uc.ctl_set_cpu_model(UC_CPU_ARM64_MAX) if hasattr(uc, 'ctl_set_cpu_model') else None

regions = []  # (addr, size, type, perm) for svcQueryMemory
def region(addr, size, typ, perm, data=None):
    uc.mem_map(addr, size, UC_PROT_ALL)
    if data: uc.mem_write(addr, bytes(data[:size]))
    regions.append((addr, size, typ, perm))

def fake_module(base, size=0x4000):
    # a module of size bytes holding nothing the plugin uses: text page (b +8, MOD0 offset), ro page, the rest data
    t = bytearray(PAGE)
    struct.pack_into('<II', t, 0, 0x14000002, 0x10)
    t[0x10:0x14] = b'MOD0'
    region(base, PAGE, 3, 5, t); region(base + PAGE, PAGE, 3, 1); region(base + 2 * PAGE, size - 2 * PAGE, 4, 3)

if not PEANUTS: fake_module(RTLD, RTLD_SIZE)
fake_module(SUB0, SUB0_SIZE)
def patch_area(end):
    if PEANUTS: region(end, PATCH_AREA, 4, 5)
patch_area(SUB0 + SUB0_SIZE)

relocate(main, M)
relocate(plug, P)
region(M, MAIN_RO, 3, 5, main)
region(M + MAIN_RO, MAIN_DATA - MAIN_RO, 3, 1, main[MAIN_RO:])
region(M + MAIN_DATA, MAIN_END - MAIN_DATA, 4, 3, main[MAIN_DATA:])
patch_area(M + MAIN_END)

plug = plug.ljust(PLUG_END, b'\0')
region(P, PLUG_TEXT_END, 3, 5, plug)
region(P + PLUG_RO, PLUG_DATA - PLUG_RO, 3, 1, plug[PLUG_RO:])
region(P + PLUG_DATA, PLUG_END - PLUG_DATA, 4, 3, plug[PLUG_DATA:])
patch_area(P + PLUG_END)
fake_module(SDK)
patch_area(SDK + 0x4000)
ALIAS, ALIAS_SIZE = 0x1000000000, 0x10000000
alias_maps = []
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
threads = {}; ticks = [0]
def svc(num):
    if num == 0x27:
        s = rd(X(0), X(1)).decode('utf-8', 'replace').rstrip('\n'); L(s); setX(0, 0); return
    if num == 0x6:  # QueryMemory(MemoryInfo*, PageInfo*, addr) wrapper passes x0=meminfo x2=addr
        a = X(2); mi = X(0)
        if a >= 1 << 39:  # past the address space: Horizon reports one Inaccessible region to the top, so a walk wraps to 0 and ends
            uc.mem_write(mi, struct.pack('<QQIIIIII', 1 << 39, (1 << 64) - (1 << 39), 0x10, 0, 0, 0, 0, 0))
            setX(0, 0); setX(1, 0); return
        if PEANUTS and not any(b <= a < b + s for (b, s, t, p) in regions):   # hle_svc.c: other host memory is reported a 4 KiB free page at a time
            uc.mem_write(mi, struct.pack('<QQIIIIII', a & ~0xFFF, PAGE, 0, 0, 0, 0, 0, 0)); setX(0, 0); setX(1, 0); return
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
    if PEANUTS and num in (0x74, 0x75, 0x40, 0x8, 0x9, 0x43):   # placeholders on Peanuts: success, no effect
        L(f'# svc {num:#x} placeholder'); setX(0, 0); return
    if PEANUTS and num == 0x2C:   # MapPhysicalMemory, mem_map_limit off: any page-aligned range inside the alias region
        a, size = X(0), X(1)
        if not size or (a | size) & 0xFFF or not (ALIAS <= a and a + size <= ALIAS + ALIAS_SIZE):
            L(f'# MapPhysicalMemory {a:#x}+{size:#x} refused'); setX(0, 0xD401); return
        uc.mem_map(a, size, UC_PROT_READ | UC_PROT_WRITE); alias_maps.append((a, size))
        L(f'# MapPhysicalMemory {a:#x}+{size:#x}'); setX(0, 0); return
    if num == 0x40: setX(0, 0); setX(1, 0x100); setX(2, 0x101); return
    if num == 0x8: threads[0x200] = (X(1), X(2)); setX(0, 0); setX(1, 0x200); return
    if num == 0x9:
        # run the receive thread's effect: exl stores the process handle at plug+0x2144e4
        uc.mem_write(P + 0x2144e4, struct.pack('<I', 0xFFFF8001)); setX(0, 0); return
    if num == 0x21: setX(0, 0); return
    if num == 0x18: setX(0, 0); setX(1, 0); return
    if num == 0x16: setX(0, 0); return
    if num == 0x1e: ticks[0] += 19200; setX(0, ticks[0]); return   # GetSystemTick: a steady count, so runs repeat (the plugin seeds its address picker from it)
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
if os.environ.get('EMU_READS', '0') == '1':   # every read of main's text (slow: millions of them while the plugin checks its sites)
    uc.hook_add(UC_HOOK_MEM_READ, on_main_read, begin=M, end=M + MAIN_TEXT_END - 1)
uc.hook_add(UC_HOOK_CODE, on_done, begin=DONE, end=DONE + 3)
def on_unmapped(uc_, access, addr, size, value, ud):
    L(f'# unmapped access {access} at {addr:#x} size {size} pc={where(uc_.reg_read(UC_ARM64_REG_PC))}'); return False
uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)

# EMU_SITES=file of main offsets (one per line): record each read of those words (and the plugin pc that made it) in site_reads
site_reads = collections.Counter()
def on_site_read(uc_, access, addr, size, value, ud):
    pc = uc_.reg_read(UC_ARM64_REG_PC)
    site_reads[(addr - M, size, where(pc))] += 1
if os.environ.get('EMU_SITES'):
    for _l in open(os.environ['EMU_SITES']):
        if _l.strip(): _a = M + int(_l, 16); uc.hook_add(UC_HOOK_MEM_READ, on_site_read, begin=_a, end=_a + 3)

# EMU_SHADOW=<flat main>: once FindModules returns, point main's text start in exl's module record (+0x10 of record 1) at an unpatched copy of
# main's text, mapped read-only elsewhere; calls into that copy are logged (the experiment: do the plugin's reads, targets and calls use that field)
SHADOW = 0x6000000000
shadow_exec = collections.Counter()
if os.environ.get('EMU_SHADOW'):
    _sh = open(os.environ['EMU_SHADOW'], 'rb').read()[:MAIN_TEXT_END]
    uc.mem_map(SHADOW, MAIN_TEXT_END, UC_PROT_ALL); uc.mem_write(SHADOW, _sh)
    def _set_shadow(uc_, addr, size, ud):
        uc_.mem_write(P + 0x2144f0 + 0x48 + 0x10, struct.pack('<Q', SHADOW))
    uc.hook_add(UC_HOOK_CODE, _set_shadow, begin=P + 0x6db40, end=P + 0x6db40)
    def _shadow_exec(uc_, addr, size, ud):
        shadow_exec[(addr - SHADOW, where(uc_.reg_read(UC_ARM64_REG_LR)))] += 1; ret(0)
    uc.hook_add(UC_HOOK_CODE, _shadow_exec, begin=SHADOW, end=SHADOW + MAIN_TEXT_END - 1)
_where0 = where
def where(a):
    if SHADOW <= a < SHADOW + MAIN_TEXT_END: return f'shadow+{a - SHADOW:#x}'
    return _where0(a)

# every hook the plugin installs: exl HookInline (0x79020: target, callback, float context) and HookFunc (0x70a50: target, replacement, trampoline)
hooks = []
def on_hook(uc_, addr, size, ud):
    kind = 'inline' if addr == P + 0x79020 else 'func'
    h = dict(kind=kind, target=where(X(0)), cb=where(X(1)), flag=X(2) & 0xffffffff, lr=where(uc_.reg_read(UC_ARM64_REG_LR)))
    if kind == 'func' and h['lr'] == 'plug+0x79084': return   # HookInline's own call of HookFunc
    if PEANUTS and X(0) - M in lazy: uc_.mem_write(X(0), lazy[X(0) - M])
    hooks.append(h); L(f"# hook {kind} {h['target']} -> {h['cb']} flag={h['flag']} from {h['lr']}")
for _o in (0x79020, 0x70a50): uc.hook_add(UC_HOOK_CODE, on_hook, begin=P + _o, end=P + _o)

# EMU_PROBE=off,off,...: print x0-x5, x19-x28 and lr each time the plugin reaches one of these offsets
def on_probe(uc_, addr, size, ud):
    regs = ' '.join(f'x{i}={X(i):#x}' for i in list(range(6)) + list(range(19, 29)))
    L(f'# probe {where(addr)} {regs} lr={where(uc_.reg_read(UC_ARM64_REG_LR))}')
for _o in filter(None, os.environ.get('EMU_PROBE', '').split(',')):
    _a = P + int(_o, 16); uc.hook_add(UC_HOOK_CODE, on_probe, begin=_a, end=_a)

text_writes = collections.Counter(); text_reads = collections.Counter(); shadow_misses = collections.Counter(); reports = collections.Counter()
if PEANUTS:
    INFO[3] = ALIAS_SIZE
    # anything writing main's text (Peanuts seals it R-X: on the device that is a fault)
    def on_text_write(uc_, access, addr, size, value, ud): text_writes[(addr - M, where(uc_.reg_read(UC_ARM64_REG_PC)))] += 1
    uc.hook_add(UC_HOOK_MEM_WRITE, on_text_write, begin=M, end=M + MAIN_RO - 1)
    # the plugin's reads of the real main's text (through the module start, +0x48): the checks that still see the IPS's branches
    def on_text_read(uc_, access, addr, size, value, ud):
        pc = uc_.reg_read(UC_ARM64_REG_PC)
        if P <= pc < P + PLUG_TEXT_END and not (PEANUTS['code'] <= pc - P < PEANUTS['end']): text_reads[(addr - M, size, pc - P)] += 1
    uc.hook_add(UC_HOOK_MEM_READ, on_text_read, begin=M, end=M + MAIN_RO - 1)
    # reads of the window outside the bytes build.py packed (they read zeros)
    _runs = [struct.unpack_from('<II', plug, PEANUTS['runs'] + 8 * i) for i in range(PEANUTS['readset_runs'])]
    _have = bytearray(PEANUTS['window'])
    for _o, _n in _runs: _have[_o:_o + _n] = b'\1' * _n
    def on_shadow_read(uc_, access, addr, size, value, ud):
        o = addr - ALIAS
        if o < len(_have) and not all(_have[o:o + size]): shadow_misses[(o, size, uc_.reg_read(UC_ARM64_REG_PC) - P)] += 1
    uc.hook_add(UC_HOOK_MEM_READ, on_shadow_read, begin=ALIAS, end=ALIAS + PEANUTS['window'] - 1)
    # the plugin's reporter (0xf920): who calls it with what
    def on_report(uc_, addr, size, ud): reports[(where(uc_.reg_read(UC_ARM64_REG_LR)), X(0) & 0xffffffff, X(1) & 0xffffffff)] += 1
    uc.hook_add(UC_HOOK_CODE, on_report, begin=P + 0xf920, end=P + 0xf920)

def peanuts_report():
    slots = struct.unpack_from(f'<{PEANUTS["n"]}Q', rd(P + PEANUTS['slots'], 8 * PEANUTS['n']))
    filled = [h['name'] for h, v in zip(PEANUTS['hooks'], slots) if v]
    empty = [(h['name'], h['gate']) for h, v in zip(PEANUTS['hooks'], slots) if not v]
    rec1 = struct.unpack_from('<4Q', rd(P + 0x2144f0 + 0x48, 32))
    return dict(slots_filled=len(filled), slots_empty=empty, record1=[hex(v) for v in rec1], alias_maps=[(hex(a), hex(s)) for a, s in alias_maps],
                main_text_writes=[(hex(a), w, n) for (a, w), n in sorted(text_writes.items())],
                main_text_reads=[(hex(a), s, hex(pc), n) for (a, s, pc), n in sorted(text_reads.items())],
                shadow_misses=[(hex(a), s, hex(pc), n) for (a, s, pc), n in sorted(shadow_misses.items())],
                reports=[(w, hex(a0), hex(a1), n) for (w, a0, a1), n in sorted(reports.items())],
                ips_word_reads=sorted({hex(pc) for (a, s, pc) in text_reads if any(a < w + 4 and w < a + s for w in ips_sites)}))

def call(addr, *args, limit=int(os.environ.get("EMU_LIMIT", 200_000_000))):
    for i, a in enumerate(args): setX(i, a)
    uc.reg_write(UC_ARM64_REG_SP, STACK + STACK_SIZE - 0x100)
    uc.reg_write(UC_ARM64_REG_LR, DONE)
    try:
        uc.emu_start(addr, DONE, count=limit)
        if uc.reg_read(UC_ARM64_REG_PC) != DONE:
            L(f'# stopped after {limit} instructions at {where(uc.reg_read(UC_ARM64_REG_PC))} lr={where(uc.reg_read(UC_ARM64_REG_LR))} x19={X(19):#x} x20={X(20):#x} x21={X(21):#x}'); notes.append('limit')
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
               hooks=hooks, shadow_exec=[(hex(a), w, n) for (a, w), n in sorted(shadow_exec.items())], site_reads=[(hex(a), n_, w, c) for (a, n_, w), c in sorted(site_reads.items())], main_calls=[(hex(a), w, n) for (a, w), n in sorted(main_calls.items())],
               write_pcs=[(where(a), n) for a, n in sorted(write_pcs.items())],
               main_reads=[(hex(a), s, hex(pc), n) for (a, s, pc), n in sorted(main_reads.items())])
    if PEANUTS:
        rep['peanuts'] = pr = peanuts_report()
        print(f"## {tag}: slots {pr['slots_filled']}/{PEANUTS['n']} filled; main text writes {len(pr['main_text_writes'])}; plugin reads of real main text "
              f"{len(pr['main_text_reads'])} (pcs {len({r[2] for r in pr['main_text_reads']})}); window reads outside the read set {len(pr['shadow_misses'])}; "
              f"reporter calls {sum(r[3] for r in pr['reports'])}; reads of IPS words through real main (pcs) {len(pr['ips_word_reads'])}; record1 {pr['record1']}")
        open(f'{OUT}.{tag}.textreads.txt', 'w').write(''.join(pc + '\n' for pc in pr['ips_word_reads']))
    json.dump(rep, open(f'{OUT}.{tag}.json', 'w'), indent=0)
    open(f'{OUT}.log', 'w', encoding='utf-8').write('\n'.join(log))
    print(f'## {tag}: main writes {len(mw)} bytes in {len(rep["main_writes"])} runs; plugin writes {len(pw)}; '
          f'main calls {len(main_calls)}; main read sites {len(main_reads)}')

if __name__ == '__main__':
    L(f'# {len(imports)} imports bound to stubs')
    if os.environ.get('EMU_LOG', '0') == '1': uc.mem_write(P + 0xad00a, b'\x01')  # the plugin's own log switch; on, it breaks hook installs
    call(P + 0x6dbd0)
    dump('init')
    # the bootstrap hook (main+0x37b5464 -> plug+0x5a0) runs once the game has mounted its content: call it with an InlineCtx of zeros
    ctx = HEAP + HEAP_SIZE - 0x1000
    uc.mem_write(ctx, bytes(0x100))
    call(P + 0x5a0, ctx)
    dump('mount')
