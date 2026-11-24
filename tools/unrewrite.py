"""Rebuild the original main image from a Peanuts pack (main.patched.bin + main.changed.tsv + main.orig.bin).
Usage: unrewrite.py <pack_dir> <out.bin>"""
import sys, os
pack, out = sys.argv[1], sys.argv[2]
img = bytearray(open(os.path.join(pack, 'main.patched.bin'), 'rb').read())
orig = open(os.path.join(pack, 'main.orig.bin'), 'rb').read()
patch_off = None
pos = 0
for line in open(os.path.join(pack, 'main.changed.tsv')):
    if line.startswith('# PATCH_OFF'):
        patch_off = int(line.split()[2], 16)
    if not line.strip() or line.startswith('#'):
        continue
    off, ln = (int(x, 16) for x in line.split()[:2])
    img[off:off + ln] = orig[pos:pos + ln]
    pos += ln
assert pos == len(orig), (pos, len(orig))
if patch_off:
    img = img[:patch_off]
open(out, 'wb').write(img)
print('restored', pos, 'bytes; image', hex(len(img)))
