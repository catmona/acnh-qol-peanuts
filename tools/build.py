#!/usr/bin/env python3
"""Build the Peanuts port of QoL Enhancements v1.1.0 (ACNH 3.0.3): a patched subsdk6, the main IPS32 and the mod zip (docs/PORT.md).

Usage: python -P -E tools/build.py --exefs <game exefs dir: main, subsdk0> [--rstb <romfs System/Resource/ResourceSizeTable.srsizetable>]
       [--mod <atmosphere/contents/01006F8002326000>] [--out out/build]
--rstb puts vanilla 3.0.3's size table in the patch file (tools/add_rstb.py), so the page can write the zip's table.

What it does to the plugin (offsets are subsdk6's; every patched word is checked against the stock one first):
- FindModules starts its QueryMemory walk at main (a far `b main+0` anchor that the loader re-aims) and counts rtld as present. It stops once it has recorded the
  module after itself (sdk), so the 4 KiB free pages Peanuts reports past the arena are never walked.
- The window lives in the plugin's own bss: a page table (one byte per page of main's text) and copies of the main text pages near each hook site (the pages
  within 64 bytes of a site, each with the page after it, so a read that runs across a page end stays in the copy). exl init (shadow_setup) copies those pages
  from the real main before any hook goes in, puts each site's original word back (the IPS word is already there by then) and fills the page table. No svc and
  no Peanuts row: Peanuts maps module bss as anonymous pages. main's record stays the real main (the plugin reaches main's data through it too). Instead, each
  plugin load that reads a word the IPS changes (docs/textreads.tsv) becomes a `b` to a thunk: it works out the load's address, xlate moves an address on a
  copied page into the window, and the load runs from there. The flags and every other register are kept. Before init, and for any other page, the page
  table says 0 and the load reads the real main.
- No code is written into main at run time. Each hook site gets a `b stub_i` from the IPS. HookFunc and HookInline only fill SLOTS[i], copy the installed word into
  the window (so the "publication" re-read sees a change), and HookFunc returns the site's trampoline. An empty slot runs the original code.
The 151 original site words (and the instructions displaced into the trampolines) come from the user's own dump at build time; nothing of the game is
stored in this repo.
"""
import argparse, hashlib, json, re, struct, sys, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nso  # noqa: E402
from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN  # noqa: E402
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TID = '01006F8002326000'
PAGE = 0x1000
PLUGIN_BUILD_ID = '0deacd54d0e3ff25262b59b3ab62436c409a5bda'
MAIN_BUILD_ID = 'ff1d1c05670db6021c85b624a710b963'

# subsdk6 addresses (QoL Enhancements v1.1.0)
RECORDS = 0x2144f0              # FindModules' 13 records of 0x48 bytes; main is record 1
REC1 = RECORDS + 0x48           # +0 module start, +0x10 text start, +0x18 text size (left real)
MASK = 0x2144e8                 # bit n: record n found
SELF_GOT = 0xb9d88              # GOT slot of __module_start
IMPL, IMPL_FLOAT = 0x7e5b4, 0x7e64c   # exl_inline_hook_impl, exl_inline_float_hook_impl
FREE = (0x71000, 0x79000)       # exl's trampoline pool, unused once the pools are off (all zero in the stock file)
FREE2 = (0x79150, 0x7e000)      # after HookInline: zero in the stock file too
WALK_END, WALK_DONE, WALK_NEXT = 0x6ead0, 0x6ead4, 0x6ea90

# patch point: (stock instruction as capstone prints it, why)
PATCHES = {
    0x6e990: ('mov x26, #0', 'FindModules: first query address -> walk_start (main base, rtld counted)'),
    0x6ea88: ('cmp x0, x26', 'FindModules after a record -> walk_check (stop after the module that follows this one)'),
    0x6db90: ('bl #0x6f100', 'exl init RwPages(main) -> shadow_setup'),
    0x6db94: ('bl #0x6e310', 'exl init process handle (svc 0x40/0x8/0x43, placeholders on Peanuts) -> nop'),
    0x70a20: ('adrp x1, #0x214000', 'pool setup (RwPages of both pools) -> ret'),
    0x70a50: ('stp x29, x30, [sp, #-0x80]!', 'HookFunc -> hook_new'),
    0x79020: ('adrp x4, #0x214000', 'HookInline -> hook_new'),
    0x7e5fc: ('ldr x20, [x19, #8]', 'inline impl: callback from the entry -> get_cb (SLOTS[i])'),
    0x7e6d8: ('ldr x20, [x19, #8]', 'inline float impl: same'),
}

KS = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
CS = Cs(CS_ARCH_ARM64, CS_MODE_ARM)


def asm(src, addr):
    # keystone 0.9.2 mis-encodes adr to a numeric address (either direction): use adrp + add for those
    def two(m):
        ind, r, t = m[1], m[2], int(m[3])
        return f'{ind}adrp {r}, {t & ~0xFFF}\n{ind}add {r}, {r}, #{t & 0xFFF}'
    src = re.sub(r'^([ \t]*)adr (x\d+), (\d+)[ \t]*$', two, src, flags=re.M)
    enc, _ = KS.asm(src, addr)
    return bytes(enc)


def console_size(head):
    """xmod.header's rule: where the last segment or bss ends, on a page"""
    segs = [struct.unpack_from('<III', head, 0x10 + i * 0x10)[1:] for i in range(3)]
    bss = struct.unpack_from('<I', head, 0x3c)[0]
    end = max(segs[0][0] + segs[0][1], segs[1][0] + segs[1][1], segs[2][0] + segs[2][1] + bss)
    return (end + PAGE - 1) & ~(PAGE - 1)


def load_hooks():
    rows = []
    for line in (REPO / 'docs/hooks.tsv').read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'): continue
        c = line.split('\t')
        r = dict(name=c[1], kind=c[2], site=int(c[4].removeprefix('main+'), 16), gate=c[6] if len(c) > 6 else '')
        same = [q for q in rows if q['site'] == r['site']]
        if same:   # UpdatePreviewActor is in two request-table entries with the same callback and install call: one hook
            assert (same[0]['name'], same[0]['kind']) == (r['name'], r['kind']), f"two hooks on main+{r['site']:#x}"
            continue
        rows.append(r)
    return rows


def load_textreads():
    """The plugin offsets of the loads that read one of the IPS's words in main (tools/emu.py EMU_LAZY's <out>.textreads.txt, the union of the runs, in
    docs/textreads.tsv): each goes through a thunk that reads the window instead"""
    out = []
    for line in (REPO / 'docs/textreads.tsv').read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#'): out.append(int(line.split('\t')[0], 16))
    return sorted(set(out))


def thunk_src(i, xlate, back, lab):
    """A thunk for load i (capstone): its address into x17, x17 through xlate (into the window when it lies in main's text), the load from [x17], back.
    x16 and x17 are kept on the stack; the flags are not touched"""
    m = re.fullmatch(r'(.*?)\[([^\]]+)\](!?)(?:, #(-?0x[0-9a-f]+|-?\d+))?', i.op_str)
    assert i.mnemonic.startswith('ld') and m, (hex(i.address), i.mnemonic, i.op_str)
    regs, mem, pre, post = m[1], m[2].split(', '), m[3], m[4]
    base = mem[0]
    # x14 and x15 come back from xlate as they went in, and the address is worked out before x16 is reused. A loaded x16 / x17 is not restored (the load
    # gives its value); a written-back x16 / x17 and an sp base (moved by the thunk's own frame) would need another form
    dest = set(re.findall(r'(?<![0-9a-z])[xw](\d+)(?![0-9])', regs))
    assert base != 'sp' and not ((pre or post) and base[1:] in ('16', '17')), (hex(i.address), i.op_str)
    restore = {frozenset(): ['ldp x16, x17, [sp]'], frozenset({'16'}): ['ldr x17, [sp, #8]'], frozenset({'17'}): ['ldr x16, [sp]'],
               frozenset({'16', '17'}): []}[frozenset(dest & {'16', '17'})]
    imm = lambda t: int(t.lstrip('#'), 0)
    ea, wb = [], []
    if len(mem) == 1: ea = [f'mov x17, {base}']
    elif mem[1].startswith('#'):
        k = imm(mem[1]); op = 'add' if k >= 0 else 'sub'
        assert abs(k) < 0x1000000, hex(i.address)
        ea = [f'{op} x17, {base}, #{abs(k) & 0xFFF}'] + ([f'{op} x17, x17, #{abs(k) >> 12}, lsl #12'] if abs(k) >> 12 else [])
        if pre: wb = [f'add {base}, {base}, #{k}' if k >= 0 else f'sub {base}, {base}, #{-k}']
    else:
        assert not pre
        ext = ', '.join(mem[2:])
        if mem[1].startswith('w') and not ext: ext = 'uxtw'
        ea = [f'add x17, {base}, {mem[1]}' + (f', {ext}' if ext else '')]
    if post is not None:
        k = imm(post); wb = [f'add {base}, {base}, #{k}' if k >= 0 else f'sub {base}, {base}, #{-k}']
    return '\n'.join(['sub sp, sp, #0x30', 'stp x16, x17, [sp]'] + ea + [f'adr x16, {lab}', f'b {xlate}', f'{lab}: {i.mnemonic} {regs}[x17]'] + restore + [
                      'add sp, sp, #0x30'] + wb + [f'b {back}'])


def decode_branch(w, at):
    """(kind, target) of a PC-relative word at main offset at, or None"""
    sx = lambda v, bits: v - ((v >> (bits - 1)) & 1) * (1 << bits)
    if w & 0x7C000000 == 0x14000000: return ('bl' if w >> 31 else 'b'), at + 4 * sx(w & 0x3FFFFFF, 26)
    if w & 0xFF000010 == 0x54000000 or w & 0x7E000000 == 0x34000000: return 'cond19', at + 4 * sx((w >> 5) & 0x7FFFF, 19)
    if w & 0x7E000000 == 0x36000000: return 'cond14', at + 4 * sx((w >> 5) & 0x3FFF, 14)
    if w & 0x9F000000 == 0x90000000:
        imm = sx(((w >> 5) & 0x7FFFF) << 2 | (w >> 29) & 3, 21)
        return 'adrp', (at & ~0xFFF) + (imm << 12)
    if w & 0x9F000000 == 0x10000000: return 'adr', None
    if w & 0x3B000000 == 0x18000000: return 'ldrlit', None
    return None


def auto_swim_off(ini):
    """docs/qol.js autoSwimOff: with auto_swim on, the character can't swim at the surface after a dive, so the zip has it off"""
    return re.sub(rb'(?m)^auto_swim[ \t]*=[ \t]*true\b', b"# Off in the Peanuts port: when on, you can't swim at the surface after a dive.\nauto_swim = false", ini, count=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exefs', required=True, help="the game's exefs (main and subsdk0, ACNH 3.0.3): read here, never copied into the repo")
    ap.add_argument('--rstb', help="the game's own ResourceSizeTable.srsizetable (3.0.3, romfs System/Resource/) for the patch file")
    ap.add_argument('--mod', default=str(REPO / f'in/switch/atmosphere/contents/{TID}'))
    ap.add_argument('--out', default=str(REPO / 'out/build'))
    a = ap.parse_args()
    exefs, mod, out = Path(a.exefs), Path(a.mod), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # the console layout xmod assumes: rtld, main, subsdk0, subsdk6, sdk back to back
    mhead = (exefs / 'main').read_bytes()[:0x100]
    assert mhead[0x40:0x60].hex().rstrip('0').startswith(MAIN_BUILD_ID), 'not ACNH 3.0.3 main'
    PB = console_size(mhead) + console_size((exefs / 'subsdk0').read_bytes()[:0x100])   # subsdk6 from main
    minfo, mimg = nso.load(str(exefs / 'main'))
    MAIN_TEXT = minfo['segs'][0]['size']
    A = lambda off: PB + off   # plugin offset -> console address (main at 0)

    pinfo, pimg = nso.load(str(mod / 'exefs/subsdk6'))
    assert pinfo['build_id'].startswith(PLUGIN_BUILD_ID), 'not QoL Enhancements v1.1.0 subsdk6'
    ptext = pinfo['segs'][0]['size']
    stock = bytes(pimg)
    for off, (want, _) in PATCHES.items():
        i = next(CS.disasm(stock[off:off + 4], off))
        assert f'{i.mnemonic} {i.op_str}' == want, (hex(off), i.mnemonic, i.op_str)
    assert not any(stock[FREE[0]:FREE[1]]) and not any(stock[FREE2[0]:FREE2[1]]), 'free run not empty'
    # the stock plugin has no far b/bl of its own
    for o in range(0, ptext & ~3, 4):
        w = struct.unpack_from('<I', stock, o)[0]
        if w & 0x7C000000 == 0x14000000:
            d = w & 0x3FFFFFF; t = o + 4 * (d - ((d & 0x2000000) << 1))
            assert 0 <= t < ptext + 0x200000, hex(o)

    hooks = load_hooks()
    n = len(hooks)
    sites = [h['site'] for h in hooks]
    # the window, in plugin bss: copies of the pages of main's text around each site word (a load of up to 64 bytes that touches the word starts and ends in
    # them: "redirect" pages, which the page table sends to the window), and the page after each, copied but not redirected, so a load that starts in a
    # redirect page and runs past it still reads main's bytes. Slots follow the page order, so neighbouring pages stay neighbours
    NPT = (MAIN_TEXT + PAGE - 1) // PAGE
    redir = {p for s in sites for p in range((s - 63) >> 12, ((s + 4 + 63) >> 12) + 1)}
    wpages = sorted(redir | {p + 1 for p in redir})
    assert max(redir) < NPT and len(wpages) < 0xFF and NPT < 0x10000

    # bss: SLOTS (one page), the page table (a byte per page of main's text: slot + 1, 0 = not redirected), the window
    data_end = pinfo['segs'][2]['moff'] + pinfo['segs'][2]['size']
    old_end = data_end + pinfo['bss']
    assert old_end % PAGE == 0
    SLOTS = old_end
    assert 8 * n <= PAGE
    PT = SLOTS + PAGE
    WIN = PT + ((NPT + PAGE - 1) & ~(PAGE - 1))
    new_bss = WIN + PAGE * len(wpages) - data_end

    # layout of the free run
    CODE = FREE[0]
    STUBS = CODE + 0x400
    TRAMPS = STUBS + 0x10 * n
    SITES = TRAMPS + 0x20 * n
    PAGES = SITES + 4 * n             # per slot: main page | 0x10000 when redirected
    ORIG = PAGES + 4 * len(wpages)    # per site: the original word as two halfwords (no table word can read as an instruction a scan would change)
    END = ORIG + 8 * n
    assert END <= FREE[1], f'{END:#x} past the free run'

    pg = lambda off: A(off) & ~0xFFF
    lo = lambda off: off & 0xFFF
    # routines, each assembled at its own address. The anchor is the area's last word: keystone 0.9.2 refuses an adr that goes backwards
    R = [
        # x17: an address in, the same address or its place in the window out; returns to x16. Uses the 0x30-byte frame its caller made: x16 and x17 at
        # [sp] are the caller's, [sp+0x10..0x28] keep x13-x15. No flags change
        ('xlate', lambda L: f"""
    stp x14, x15, [sp, #0x10]
    str x13, [sp, #0x20]
    adrp x15, {pg(REC1)}
    ldr x15, [x15, #{lo(REC1)}]
    sub x15, x17, x15
    tbnz x15, #63, xl_out
    lsr x14, x15, #12
    movz x13, #{NPT}
    sub x13, x14, x13
    tbz x13, #63, xl_out
    adrp x13, {pg(PT)}
    add x13, x13, #{lo(PT)}
    ldrb w13, [x13, x14]
    cbz w13, xl_out
    sub x13, x13, #1
    adrp x14, {pg(WIN)}
    add x14, x14, #{lo(WIN)}
    add x14, x14, x13, lsl #12
    and x15, x15, #0xfff
    add x17, x14, x15
xl_out:
    ldr x13, [sp, #0x20]
    ldp x14, x15, [sp, #0x10]
    br x16"""),
        ('walk_start', lambda L: f"""
    adr x16, {A(L['anchor'])}
    ldr w17, [x16]
    sbfx x17, x17, #0, #26
    add x26, x16, x17, lsl #2
    mov w19, #1
    adrp x16, {pg(MASK)}
    ldr x17, [x16, #{lo(MASK)}]
    orr x17, x17, #1
    str x17, [x16, #{lo(MASK)}]
    ret"""),
        ('walk_check', lambda L: f"""
    sub w16, w19, #2
    mov w17, #0x48
    umull x16, w16, w17
    ldr x16, [x25, x16]
    adrp x17, {pg(SELF_GOT)}
    ldr x17, [x17, #{lo(SELF_GOT)}]
    cmp x16, x17
    b.ne wc_go
    ldp x16, x17, [x25, #0x48]
    stp x16, x17, [x25]
    ldp x16, x17, [x25, #0x58]
    stp x16, x17, [x25, #0x10]
    ldp x16, x17, [x25, #0x68]
    stp x16, x17, [x25, #0x20]
    ldp x16, x17, [x25, #0x78]
    stp x16, x17, [x25, #0x30]
    ldr x16, [x25, #0x88]
    str x16, [x25, #0x40]
    b {A(WALK_END)}
wc_go:
    cmp x0, x26
    b.lo {A(WALK_DONE)}
    b {A(WALK_NEXT)}"""),
        # copy main's pages into the window slot by slot (setting the page table for the redirect ones), then put each site's original word back there
        ('shadow_setup', lambda L: f"""
    sub sp, sp, #0x30
    adrp x9, {pg(REC1)}
    ldr x9, [x9, #{lo(REC1)}]
    adr x10, {A(PAGES)}
    adrp x11, {pg(WIN)}
    add x11, x11, #{lo(WIN)}
    adrp x12, {pg(PT)}
    add x12, x12, #{lo(PT)}
    movz w13, #{len(wpages)}
    mov w8, #1
ss_page:
    ldr w14, [x10], #4
    and x15, x14, #0xffff
    tbz w14, #16, ss_copy
    strb w8, [x12, x15]
ss_copy:
    add x14, x9, x15, lsl #12
    mov w15, #{PAGE // 16}
ss_cp:
    ldp x6, x7, [x14], #16
    stp x6, x7, [x11], #16
    subs w15, w15, #1
    b.ne ss_cp
    add w8, w8, #1
    subs w13, w13, #1
    b.ne ss_page
    adr x10, {A(SITES)}
    adr x12, {A(ORIG)}
    movz w14, #{n}
ss_orig:
    ldr w15, [x10], #4
    ldp w6, w7, [x12], #8
    orr w6, w6, w7, lsl #16
    add x17, x9, x15
    adr x16, ss_put
    b {A(L['xlate'])}
ss_put:
    str w6, [x17]
    subs w14, w14, #1
    b.ne ss_orig
    add sp, sp, #0x30
    ret"""),
        ('hook_new', lambda L: f"""
    adrp x9, {pg(REC1)}
    ldr x15, [x9, #{lo(REC1)}]
    sub x10, x0, x15
    adr x11, {A(SITES)}
    mov w12, #0
hk_loop:
    ldr w13, [x11, w12, uxtw #2]
    cmp x13, x10
    b.eq hk_found
    add w12, w12, #1
    cmp w12, #{n}
    b.ne hk_loop
    mov x0, #0
    ret
hk_found:
    adrp x9, {pg(SLOTS)}
    add x9, x9, #{lo(SLOTS)}
    str x1, [x9, x12, lsl #3]
    ldr w13, [x15, x10]
    add x17, x15, x10
    sub sp, sp, #0x30
    adr x16, hk_put
    b {A(L['xlate'])}
hk_put:
    add sp, sp, #0x30
    sub x9, x17, x15
    cmp x9, x10
    b.eq hk_ret
    str w13, [x17]
hk_ret:
    adr x0, {A(TRAMPS)}
    add x0, x0, x12, lsl #5
    ret"""),
        ('get_cb', lambda L: f"""
    adr x16, {A(STUBS)}
    sub x20, x19, x16
    lsr x20, x20, #4
    adrp x16, {pg(SLOTS)}
    add x16, x16, #{lo(SLOTS)}
    ldr x20, [x16, x20, lsl #3]
    cbnz x20, gc_ret
    adr x20, gc_noop
gc_ret:
    ret
gc_noop:
    ret"""),
    ]
    labels, at, code = {'anchor': STUBS - 4}, CODE, b''
    for name, src in R:
        labels[name] = at
        try: b = asm(src(labels), A(at))
        except Exception as e: raise SystemExit(f'{name}: {e}\n{src(labels)}')
        code += b; at += len(b)
        at = (at + 0xF) & ~0xF; code = code.ljust(at - CODE, b'\0')
    assert at <= STUBS - 4, f'routines end at {at:#x}'
    code = code.ljust(STUBS - 4 - CODE, b'\0') + asm('b 0', A(STUBS - 4))
    img = bytearray(pimg)
    img[CODE:CODE + len(code)] = code
    far = {}   # plugin offset -> intended main target of each far b/bl

    def put(off, b):
        img[off:off + len(b)] = b

    def far_b(off, target, link=False):
        put(off, asm(f'{"bl" if link else "b"} {target}', A(off))); far[off] = target
    far[labels['anchor']] = 0

    sitebytes = bytearray()
    displaced = {}
    for i, h in enumerate(hooks):
        s, st, tr = h['site'], STUBS + 0x10 * i, TRAMPS + 0x20 * i
        assert s + 4 < MAIN_TEXT
        if h['kind'] == 'func':
            put(st, asm(f'adrp x16, {pg(SLOTS)}\nldr x16, [x16, #{lo(SLOTS) + 8 * i}]\ncbz x16, {A(tr)}\nbr x16', A(st)))
        else:
            impl = IMPL_FLOAT if h['kind'] == 'inline-float' else IMPL
            put(st, asm(f'stur x30, [sp, #-0x10]\nbl {A(impl)}\nldur x30, [sp, #-0x10]\nb {A(tr)}', A(st)))
        w = struct.unpack_from('<I', mimg, s)[0]
        k = decode_branch(w, s)
        if k is None:
            put(tr, struct.pack('<I', w)); far_b(tr + 4, s + 4)
        else:
            kind, t = k
            displaced[h['name']] = f'{kind} {t:#x}' if t is not None else kind
            if kind == 'b': far_b(tr, t)
            elif kind == 'bl': far_b(tr, t, True); far_b(tr + 4, s + 4)
            elif kind in ('cond19', 'cond14'):
                bits = 0x7FFFF if kind == 'cond19' else 0x3FFF
                put(tr, struct.pack('<I', (w & ~(bits << 5)) | (2 << 5)))
                far_b(tr + 4, s + 4); far_b(tr + 8, t)
            elif kind == 'adrp':
                d = w & 0x1F
                parts = [f'adrp x{d}, {pg(REC1)}', f'ldr x{d}, [x{d}, #{lo(REC1)}]']
                kp = t >> 12
                while kp:
                    c = min(kp, 0xFFF); parts.append(f'add x{d}, x{d}, #{c}, lsl #12'); kp -= c
                b = asm('\n'.join(parts), A(tr)); assert len(b) <= 0x1C, h['name']
                put(tr, b); far_b(tr + len(b), s + 4)
            else:
                raise SystemExit(f'{h["name"]}: displaced {kind} at main+{s:#x} not handled')
        sitebytes += struct.pack('<I', s)
    put(SITES, bytes(sitebytes))
    put(PAGES, b''.join(struct.pack('<I', p | (0x10000 if p in redir else 0)) for p in wpages))
    put(ORIG, b''.join(struct.pack('<II', w & 0xFFFF, w >> 16) for w in (struct.unpack_from('<I', mimg, s)[0] for s in sites)))

    # patch points
    put(0x6e990, asm(f'bl {A(labels["walk_start"])}', A(0x6e990)))
    put(0x6ea88, asm(f'b {A(labels["walk_check"])}', A(0x6ea88)))
    put(0x6db90, asm(f'bl {A(labels["shadow_setup"])}', A(0x6db90)))
    put(0x6db94, asm('nop', 0))
    put(0x70a20, asm('ret', 0))
    put(0x70a50, asm(f'b {A(labels["hook_new"])}', A(0x70a50)))
    put(0x79020, asm(f'b {A(labels["hook_new"])}', A(0x79020)))
    put(0x7e5fc, asm(f'bl {A(labels["get_cb"])}', A(0x7e5fc)))
    put(0x7e6d8, asm(f'bl {A(labels["get_cb"])}', A(0x7e6d8)))

    # the loads that read an IPS word: a b to a thunk that reads the window. Thunks fill the free run after the tables, then the run after HookInline
    areas, ai, thunks = [((END + 0xF) & ~0xF, FREE[1]), FREE2], 0, {}
    at = areas[0][0]
    for o in load_textreads():
        assert o < CODE and o not in PATCHES, hex(o)
        i = next(CS.disasm(stock[o:o + 4], o))
        src = thunk_src(i, A(labels['xlate']), A(o + 4), f'tk{o:x}')
        b = asm(src, A(at))
        if at + len(b) > areas[ai][1]:
            ai += 1; assert ai < len(areas), 'the thunks do not fit'; at = areas[ai][0]; b = asm(src, A(at))
        put(at, b); put(o, asm(f'b {A(at)}', A(o))); thunks[o] = at; at += len(b)

    # checks: every b/bl in the new text is either inside the plugin or one of the far branches meant for main's text; no data word looks like one
    for o in range(0, ptext & ~3, 4):
        w = struct.unpack_from('<I', img, o)[0]
        if w == struct.unpack_from('<I', stock, o)[0] or w & 0x7C000000 != 0x14000000: continue
        d = w & 0x3FFFFFF; t = o + 4 * (d - ((d & 0x2000000) << 1))
        if o in far:
            assert PB + t == far[o] and 0 <= far[o] < MAIN_TEXT, hex(o)
        else:
            assert 0 <= t < ptext, f'{o:#x}: unintended far branch'
            assert not SITES <= o < END, f'{o:#x}: a data word reads as a branch'
    for o in range(SITES, END, 4):
        w = struct.unpack_from('<I', img, o)[0]
        assert w >> 26 == 0, hex(o)   # bits 26-31 clear: no b/bl, adr/adrp, ldr literal or svc pattern can match
    for o, t in far.items():
        assert abs(PB + o - t) < 1 << 27

    # main IPS32: a b stub_i at each site, the console distance (the loader re-aims it)
    ips = bytearray(b'IPS32')
    bw = {}
    for i, s in enumerate(sorted(sites)):
        st = STUBS + 0x10 * sites.index(s)
        wd = asm(f'b {A(st)}', s); bw[s] = wd
        ips += struct.pack('>IH', 0x100 + s, 4) + wd
    ips += b'EEOF'

    # NSO: uncompressed segments, hashes of each, bss one page larger
    head = bytearray(open(mod / 'exefs/subsdk6', 'rb').read()[:0x100])
    segs = [bytes(img[s['moff']:s['moff'] + s['size']]) for s in pinfo['segs']]
    foff = 0x100
    body = b''
    for k, s in enumerate(pinfo['segs']):
        struct.pack_into('<III', head, 0x10 + k * 0x10, foff + len(body), s['moff'], s['size'])
        struct.pack_into('<I', head, 0x60 + k * 4, s['size'])
        head[0xA0 + k * 0x20:0xC0 + k * 0x20] = hashlib.sha256(segs[k]).digest()
        body += segs[k]
    struct.pack_into('<I', head, 0x3C, new_bss)
    struct.pack_into('<I', head, 0x0C, 0x38)   # not compressed, hash checked
    sub6 = bytes(head) + body

    ipsname = f'{MAIN_BUILD_ID}.ips'
    # the patch the web patcher (web/index.html) applies to a stock download: the bytes this build changes in the plugin image, the new header and the
    # main IPS. It holds the original word at each site (from the game), so it goes in Releases only, never in the repository
    diff = [o for s in pinfo['segs'] for o in range(s['moff'], s['moff'] + s['size']) if img[o] != stock[o]]
    runs = []
    for o in diff:
        if runs and o - runs[-1][1] < 16: runs[-1][1] = o + 1
        else: runs.append([o, o + 1])
    b64 = lambda b: __import__('base64').b64encode(bytes(b)).decode()
    sha = lambda b: hashlib.sha256(bytes(b)).hexdigest()
    patch = dict(format=1, tid=TID, plugin_build_id=PLUGIN_BUILD_ID, stock_image_sha256=sha(stock), header=b64(head),
                 edits=[[a, b64(img[a:e])] for a, e in runs], subsdk6_sha256=sha(sub6), ips_name=ipsname, ips=b64(ips))
    if a.rstb:
        from add_rstb import rstb_field
        patch['rstb'] = rstb_field(Path(a.rstb))
    re_img = bytearray(stock)
    for a, e in runs: re_img[a:e] = img[a:e]
    assert bytes(head) + b''.join(re_img[s['moff']:s['moff'] + s['size']] for s in pinfo['segs']) == sub6, 'patch does not rebuild subsdk6'
    (out / 'qol-peanuts-patch.json').write_text(json.dumps(patch))
    (out / 'subsdk6').write_bytes(sub6)
    (out / ipsname).write_bytes(ips)
    layout = dict(plugin_from_main=PB, code=CODE, stubs=STUBS, tramps=TRAMPS, sites_table=SITES, pages_table=PAGES, orig=ORIG, end=END,
                  slots=SLOTS, page_table=PT, window=WIN, window_pages=wpages, redirect_pages=sorted(redir), bss=new_bss, labels=labels, n=n,
                  hooks=[dict(name=h['name'], kind=h['kind'], site=h['site'], gate=h['gate']) for h in hooks], displaced=displaced,
                  far=len(far), thunks={hex(k): hex(v) for k, v in thunks.items()}, thunk_end=at)
    (out / 'layout.json').write_text(json.dumps(layout, indent=1))
    zpath = out / 'qol-enhancements-peanuts.zip'
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        base = f'atmosphere/contents/{TID}'
        z.writestr(f'{base}/exefs/subsdk6', sub6)
        z.write(mod / 'exefs/main.npdm', f'{base}/exefs/main.npdm')
        for f in sorted((mod / 'romfs').rglob('*')):
            if not f.is_file(): continue
            rel = f.relative_to(mod / 'romfs').as_posix()
            if rel == 'qol-enhancements/config/controls.ini': z.writestr(f'{base}/romfs/{rel}', auto_swim_off(f.read_bytes()))
            else: z.write(f, f'{base}/romfs/{rel}')
        z.writestr(f'atmosphere/exefs_patches/qol-peanuts/{ipsname}', bytes(ips))
    size = (data_end + new_bss + PAGE - 1) & ~(PAGE - 1)
    print(f'subsdk6 at main+{PB:#x}; {n} hooks; {len(far)} far branches; window {len(wpages)} pages ({len(redir)} redirected) in bss at {WIN:#x}; '
          f'free run used {CODE:#x}-{END:#x} of {FREE[1]:#x}; {len(thunks)} thunks end at {at:#x}; bss +{new_bss - pinfo["bss"]:#x}; image {size / 2**20:.2f} MiB')
    print(f'displaced PC-relative: {displaced}')
    print(f'wrote {out / "subsdk6"}, {out / ipsname}, {zpath} ({zpath.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
