"""Check hook targets (and their 16-byte fingerprint windows) against Peanuts' main.changed.tsv.

Usage: check_changed.py <main.changed.tsv> <hooks.tsv from hooks_static.py> [plugin.bin]
With plugin.bin, the plugin's signature table (u32 main offset + 16 expected bytes, stride 0x18 at 0x9dfd8)
is checked too.
"""
import sys, bisect, struct, re
runs = []
for line in open(sys.argv[1]):
    if line.startswith('#'): continue
    a, b = line.split()[:2]; runs.append((int(a, 16), int(b, 16)))
runs.sort(); starts = [r[0] for r in runs]
def hits(off, n):
    k = bisect.bisect_right(starts, off + n - 1) - 1
    out = []
    while k >= 0 and runs[k][0] + runs[k][1] > off:
        out.append(runs[k]); k -= 1
    return out
site_hit = win_hit = 0
for line in open(sys.argv[2]):
    p = line.rstrip('\n').split('\t')
    if len(p) < 4: continue
    m = re.search(r'main\+~?(0x[0-9a-f]+)', p[3])
    if not m: continue
    t = int(m.group(1), 16)
    h4, h16 = hits(t, 4), hits(t, 16)
    site_hit += bool(h4); win_hit += bool(h16)
    if h16: print(f'{p[1]}\tmain+{t:#x}\tsite={"CHANGED" if h4 else "ok"}\twindow16=' + ','.join(f'{a:#x}+{b:#x}' for a, b in h16))
print(f'# hook sites changed: {site_hit}; fingerprint windows touching a change: {win_hit}')
if len(sys.argv) > 3:
    img = open(sys.argv[3], 'rb').read(); n = 0; bad = 0
    for k in range(497):
        off = struct.unpack_from('<I', img, 0x9dfd8 + k * 0x18)[0]; n += 1
        if hits(off, 16): bad += 1
    print(f'# signature records: {n}, touching a change: {bad}')
