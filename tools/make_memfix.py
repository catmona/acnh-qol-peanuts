"""Make the ACNH memory fix: a standalone code mod for ACNH 3.0.3 (main build ff1d1c05...), one IPS32 with two words.
Usage: make_memfix.py <extra MiB> <out dir> [--main <decompressed main image>]

ACNH draws repeated models out of a fixed 22 MiB heap, "GfxDrawArrayHeap". Mods with many new model names (the
Jubbsticks port's 25 UnitIcon models) fill it, the allocator returns NULL and the game crashes at the title
(pc=sdk+0x582b2c lr=main+0x151ba24). The fix grows that heap and its parent chain's root, cScene, by the same
amount, so Scene keeps its vanilla free room. The memory comes out of cOthers, which takes the rest of the app heap
and leaves about 136 MB unused through title and island load. See docs/PORT.md, "The memory fix".

Words (file offset = main offset + 0x100, the NSO header):
  main+0x1563ba0  mov w0,#0x1600000 (GfxDrawArrayHeap size, MOVZ lsl 16)  -> mov w0,#(22 + extra) MiB
  main+0x404d678  0x23d00000 (cScene, the fifth entry of the heap size table) -> 0x23d00000 + extra MiB

Writes <out dir>/acnh-memory-fix-peanuts.zip (atmosphere/exefs_patches/acnh-memory-fix/<build id>.ips) and the bare
.ips, and prints the IPS as base64 for the patcher pages (MEMFIX.ips). --main checks both words hold their vanilla
values first."""
import sys, os, struct, base64, zipfile, hashlib

BUILD_ID = 'ff1d1c05670db6021c85b624a710b963'
SET = 'acnh-memory-fix'
HEAP_SITE, HEAP_MIB = 0x1563ba0, 22
SCENE_SITE, SCENE = 0x404d678, 0x23d00000
MIB = 1 << 20


def movz_w0_lsl16(value):
    assert value % (1 << 16) == 0 and value >> 16 < 1 << 16, hex(value)
    return 0x52a00000 | ((value >> 16) << 5)


def ips(extra_mib):
    recs = [(HEAP_SITE, struct.pack('<I', movz_w0_lsl16((HEAP_MIB + extra_mib) * MIB))),
            (SCENE_SITE, struct.pack('<I', SCENE + extra_mib * MIB))]
    return b'IPS32' + b''.join(struct.pack('>IH', off + 0x100, len(d)) + d for off, d in recs) + b'EEOF'


def main():
    a = sys.argv[1:]
    if len(a) < 2: sys.exit(__doc__)
    extra, out = int(a[0]), a[1]
    assert 0 < extra <= 64, 'cOthers has about 136 MB spare; keep the raise small'
    if '--main' in a:
        img = open(a[a.index('--main') + 1], 'rb').read()
        assert img[HEAP_SITE:HEAP_SITE + 4] == struct.pack('<I', movz_w0_lsl16(HEAP_MIB * MIB)), 'heap word is not vanilla 3.0.3'
        assert img[SCENE_SITE:SCENE_SITE + 4] == struct.pack('<I', SCENE), 'cScene word is not vanilla 3.0.3'
        print('main: both words are vanilla 3.0.3')
    b = ips(extra)
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, f'{SET}-plus{extra}mib.ips'), 'wb').write(b)
    zp = os.path.join(out, 'acnh-memory-fix-peanuts.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_STORED) as z:
        z.writestr(f'atmosphere/exefs_patches/{SET}/{BUILD_ID}.ips', b)
    print(f'+{extra} MiB: GfxDrawArrayHeap {HEAP_MIB + extra} MiB, cScene {SCENE + extra * MIB:#x}')
    print('ips sha256', hashlib.sha256(b).hexdigest(), len(b), 'bytes')
    print('MEMFIX.ips =', base64.b64encode(b).decode())


if __name__ == '__main__':
    main()
