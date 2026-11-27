"""Three-way merge of a mod's StaticParam.pack into Peanuts' 60 fps variant pack.

Why: at the 60 fps frame cap Peanuts boots "variant 60" and puts <pack>/60/romfs first in
DM_ROMFS_OVERLAY. That romfs carries tmouh's 60 FPS StaticParam.pack, so any mod that ships its
own Pack/StaticParam.pack (River Hopping in ACNH-Combined widens the no-pole river hop) loses
every change at 60 fps.

How: base = vanilla pack, ours = variant pack, theirs = each mod pack. For every BYML entry,
every 4-byte scalar (int, float, bool, uint) a mod changed against vanilla is written into the
variant pack in place, unless the variant changed the same value too (then the variant's frame
rate value wins and the clash is listed). Changes smaller than 0.1% (float drift from a mod built
on another game version) are skipped. Structure is never changed, so the SARC layout stays as is.

Usage: merge_60_pack.py <vanilla pack> <variant 60 pack> <out> <mod pack> [<mod pack> ...]
"""
import struct
import sys


def sarc_entries(b):
    """name -> (absolute data start, data bytes)"""
    assert b[:4] == b'SARC', 'not a SARC'
    doff = struct.unpack_from('<I', b, 0xC)[0]
    assert b[0x14:0x18] == b'SFAT'
    n = struct.unpack_from('<H', b, 0x1A)[0]
    nt = 0x20 + 16 * n + 8
    out = {}
    for i in range(n):
        h, attr, s, e = struct.unpack_from('<IIII', b, 0x20 + 16 * i)
        if attr >> 24:
            o = nt + (attr & 0xFFFFFF) * 4
            name = b[o:b.index(b'\0', o)].decode()
        else:
            name = '%08x' % h
        out[name] = (doff + s, b[doff + s:doff + e])
    return out


SCALAR = {0xD0: '<?', 0xD1: '<i', 0xD2: '<f', 0xD3: '<I'}


def byml_slots(b):
    """path -> (offset, type) for every 4-byte scalar slot of a BYML v2+ document"""
    if b[:2] != b'YB':
        return {}
    ko, _, ro = struct.unpack_from('<III', b, 4)
    if not ko or not ro:
        return {}
    n = struct.unpack_from('<I', b, ko)[0] >> 8
    offs = struct.unpack_from('<%dI' % n, b, ko + 4)
    keys = [b[ko + x:b.index(b'\0', ko + x)].decode() for x in offs]
    out = {}

    def walk(o, p):
        t = b[o]
        n = struct.unpack_from('<I', b, o)[0] >> 8
        items = []
        if t == 0xC0:
            ts = b[o + 4:o + 4 + n]
            vo = (o + 4 + n + 3) & ~3
            items = [(p + '[%d]' % i, ts[i], vo + 4 * i) for i in range(n)]
        elif t == 0xC1:
            for i in range(n):
                e = o + 4 + 8 * i
                ki = int.from_bytes(b[e:e + 3], 'little')
                items.append((p + '/' + keys[ki], b[e + 3], e + 4))
        for q, tt, so in items:
            if tt in (0xC0, 0xC1):
                walk(struct.unpack_from('<I', b, so)[0], q)
            elif tt in SCALAR:
                out[q] = (so, tt)

    walk(ro, '')
    return out


def value(b, slot):
    o, t = slot
    return struct.unpack_from(SCALAR[t], b, o)[0]


def tiny(a, c):
    if isinstance(a, float) and isinstance(c, float):
        return abs(a - c) <= 1e-3 * max(abs(a), abs(c), 1e-6)
    return False


def main(argv):
    if len(argv) < 5:
        sys.exit(__doc__)
    van = sarc_entries(open(argv[1], 'rb').read())
    ours_b = bytearray(open(argv[2], 'rb').read())
    ours = sarc_entries(bytes(ours_b))
    ported = clashes = drift = structural = 0
    for mod_path in argv[4:]:
        theirs = sarc_entries(open(mod_path, 'rb').read())
        for name, (_, tb) in theirs.items():
            if name not in van or name not in ours:
                print('skip %s: not in both vanilla and the variant' % name)
                structural += 1
                continue
            vb = van[name][1]
            if tb == vb:
                continue
            start, ob = ours[name]
            vs, os_, ts = byml_slots(vb), byml_slots(ob), byml_slots(tb)
            if not vs:
                print('skip %s: changed but not a BYML this tool reads' % name)
                structural += 1
                continue
            extra = set(ts) ^ set(vs)
            if extra:
                print('note %s: %d paths differ in shape from vanilla, left as the variant has them'
                      % (name, len(extra)))
            for p, slot in ts.items():
                if p not in vs or p not in os_ or vs[p][1] != slot[1] or os_[p][1] != slot[1]:
                    continue
                v0, v1, v2 = value(vb, vs[p]), value(ob, os_[p]), value(tb, slot)
                if v2 == v0:
                    continue
                if tiny(v0, v2):
                    drift += 1
                    continue
                if v1 != v0:
                    print('clash %s %s: vanilla %r, variant %r, mod %r -> keep variant'
                          % (name, p, v0, v1, v2))
                    clashes += 1
                    continue
                o = start + os_[p][0]
                ours_b[o:o + 4] = tb[slot[0]:slot[0] + 4]
                print('port %s %s: %r -> %r' % (name, p, v0, v2))
                ported += 1
    open(argv[3], 'wb').write(ours_b)
    print('ported %d, clashes kept as variant %d, float drift skipped %d, entries skipped %d'
          % (ported, clashes, drift, structural))


if __name__ == '__main__':
    main(sys.argv)
