"""List the hook requests the Core plugin passes to its hook-plan function.

Usage: hooks_static.py <plugin.bin> [plan_fn_offset=0xfd60] [window=0x1000]

Each request is a 0x30-byte record on the caller's stack: +0 name (char*), +8 callback (plugin code),
+0x10 target (offset in main), +0x18 16 expected bytes, +0x28 u32, +0x2c enabled byte. For every
`bl plan_fn`, the code before it (up to `window` bytes back) is run through a small symbolic tracker
(immediates, adrp/add, sp-relative pointers, stack stores) and the records at x1 (count x2) are printed.
A field the tracker could not resolve prints as '?'.
"""
import sys, struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from capstone.arm64 import ARM64_OP_REG, ARM64_OP_IMM, ARM64_OP_MEM, ARM64_REG_SP

img = open(sys.argv[1], 'rb').read()
PLAN = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0xfd60
WIN = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x1000
TEXT_END = 0x94000

md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True

def cstr(o):
    if not (0 <= o < len(img)): return None
    e = img.find(b'\0', o); s = img[o:e]
    return s.decode() if 0 < len(s) < 120 and all(32 <= c < 127 for c in s) else None

def plan_calls():
    for o in range(0, TEXT_END, 4):
        w = struct.unpack_from('<I', img, o)[0]
        if w >> 26 == 0x25:
            d = w & 0x3ffffff
            if o + 4 * (d - ((d & 0x2000000) << 1)) == PLAN: yield o

def X(name):  # canonical 64-bit register name
    if name in ('sp', 'wsp'): return 'sp'
    return 'x' + name[1:] if name[0] in 'wx' else name

def track(site, clobber=True):
    regs, mem = {'sp': ('sp', 0)}, {}
    start = max(0, site - WIN)
    # start at a function boundary if one is in the window: the last `ret` or unconditional branch
    for i in md.disasm(img[start:site], start):
        m, ops = i.mnemonic, i.operands
        r = lambda k: X(i.reg_name(ops[k].reg)) if ops[k].type == ARM64_OP_REG else None
        dst = r(0) if ops and ops[0].type == ARM64_OP_REG else None
        def val(k):
            return regs.get(r(k)) if ops[k].type == ARM64_OP_REG else None
        if m.startswith('st') and ops[-1].type == ARM64_OP_MEM:
            mo = ops[-1].mem
            base = regs.get(X(i.reg_name(mo.base)))
            if isinstance(base, tuple):
                off = base[1] + mo.disp
                nregs = len(ops) - 1 if m in ('stp', 'stnp') else 1
                for k in range(nregs):
                    size = 4 if i.reg_name(ops[k].reg)[0] == 'w' else (16 if i.reg_name(ops[k].reg)[0] == 'q' else 8)
                    mem[off + k * size] = (val(k), size)
            continue
        if m.startswith(('cmp', 'cmn', 'tst', 'cb', 'tb', 'b.', 'prfm', 'nop')): continue
        if m in ('bl', 'blr'):
            if clobber: regs = {k: v for k, v in regs.items() if k == 'sp' or k in [f'x{n}' for n in range(19, 30)]}; continue
        if dst is None: continue
        v = None
        if m in ('mov', 'movz', 'orr') and len(ops) == 2:
            v = ops[1].imm & (1 << 64) - 1 if ops[1].type == ARM64_OP_IMM else val(1)
        elif m == 'movn' and ops[1].type == ARM64_OP_IMM: v = ~(ops[1].imm << (ops[1].shift.value or 0)) & (1 << 64) - 1
        elif m == 'movk':
            old = regs.get(dst)
            if isinstance(old, int): sh = ops[1].shift.value or 0; v = old & ~(0xffff << sh) | (ops[1].imm << sh)
        elif m in ('adrp', 'adr'): v = ops[1].imm
        elif m in ('add', 'sub') and len(ops) == 3 and ops[2].type == ARM64_OP_IMM:
            b, imm = val(1), ops[2].imm * (1 if m == 'add' else -1)
            v = (b[0], b[1] + imm) if isinstance(b, tuple) else (b + imm if isinstance(b, int) else None)
        if m == 'mov' and len(ops) == 2 and r(1) == 'sp': v = ('sp', regs['sp'][1])
        if dst == 'sp' and not isinstance(v, tuple): v = ('sp', 0)  # frame setup: keep sp symbolic
        regs[dst] = v
    return regs, mem

def field(mem, off, size=8):
    e = mem.get(off)
    return e[0] if e and e[1] >= size or (e and e[1] == size) else None

def records(site, clobber=True):
    regs, mem = track(site, clobber)
    base, n = regs.get('x1'), regs.get('x2')
    if not isinstance(base, tuple) or not isinstance(n, int) or not 0 < n < 64: return None, n
    out = []
    for k in range(n):
        o = base[1] + k * 0x30
        name, cb, tgt = field(mem, o), field(mem, o + 8), field(mem, o + 0x10)
        en = mem.get(o + 0x2c)
        out.append((cstr(name) if isinstance(name, int) else None, cb, tgt))
    return out, n

if __name__ == '__main__':
    fmt = lambda v: f'{v:#x}' if isinstance(v, int) else (f'~{v[1]:#x}' if isinstance(v, tuple) and isinstance(v[1], int) else '?')
    for s in plan_calls():
        recs, n = records(s)
        loose, _ = records(s, clobber=False)  # values carried across a call: only used to fill gaps, marked '~'
        if recs and loose and len(loose) == len(recs):
            recs = [tuple(a if a is not None else (('~', b) if b is not None else None) for a, b in zip(r, l)) for r, l in zip(recs, loose)]
        if recs is None:
            print(f'plug+{s:#x}  (could not resolve request array; x2={n})'); continue
        for name, cb, tgt in recs:
            print(f'plug+{s:#x}\t{name or "?"}\tcb={fmt(cb)}\tmain+{fmt(tgt)}')
