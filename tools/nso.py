"""NSO0 decompress -> flat image + header info. Usage: nso.py in.nso out.bin"""
import sys, struct, json, hashlib
import lz4.block

def load(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'NSO0', d[:4]
    flags = struct.unpack_from('<I', d, 0xC)[0]
    segs = []
    for i in range(3):
        foff, moff, size = struct.unpack_from('<III', d, 0x10 + i * 0x10)
        csize = struct.unpack_from('<I', d, 0x60 + i * 4)[0]
        segs.append(dict(foff=foff, moff=moff, size=size, csize=csize, comp=bool(flags & (1 << i))))
    bss = struct.unpack_from('<I', d, 0x3C)[0]
    build_id = d[0x40:0x60].hex()
    mod_name_off, mod_name_size = struct.unpack_from('<II', d, 0x1C)
    ro_rel = struct.unpack_from('<IIIIII', d, 0x88)  # api_info, dynstr, dynsym (off,size each)
    end = max(s['moff'] + s['size'] for s in segs)
    img = bytearray(end)
    for s in segs:
        raw = d[s['foff']:s['foff'] + s['csize']]
        data = lz4.block.decompress(raw, uncompressed_size=s['size']) if s['comp'] else raw
        assert len(data) == s['size']
        img[s['moff']:s['moff'] + s['size']] = data
    return dict(segs=segs, bss=bss, build_id=build_id, flags=flags, ro_rel=ro_rel), img

if __name__ == '__main__':
    info, img = load(sys.argv[1])
    open(sys.argv[2], 'wb').write(img)
    print(json.dumps(info, indent=1))
