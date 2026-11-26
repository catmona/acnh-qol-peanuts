"""Adds vanilla ACNH 3.0.3's ResourceSizeTable.srsizetable to the web patcher's patch file, as its 'rstb' field.

    python tools/add_rstb.py <vanilla ResourceSizeTable.srsizetable> [--patch docs/qol-peanuts-patch.json]

The page starts the size table it writes from this one (docs/qol.js, sizeTable). The table is game data, so like the rest
of the patch file it goes in Releases only, never in the repository. build.py --rstb does the same for a fresh build.
The table is taken from your own 3.0.3 romfs (System/Resource/), unchanged, and must match 3.0.3's hash.
"""
import argparse, base64, hashlib, json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VANILLA_SHA256 = '8b53c66ad030ce87662285d555083813ac5f3b4655071abe7de4e4cb8aa12402'   # 3.0.3, Yaz0 as in the romfs, 399,543 bytes


def rstb_field(table: Path) -> dict:
    raw = table.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    assert raw[:4] == b'Yaz0', f'{table}: not a Yaz0 file'
    assert sha == VANILLA_SHA256, f'{table}: not the vanilla ACNH 3.0.3 table (sha256 {sha})'
    return dict(sha256=sha, data=base64.b64encode(raw).decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('table')
    ap.add_argument('--patch', default=str(REPO / 'docs/qol-peanuts-patch.json'))
    a = ap.parse_args()
    p = Path(a.patch)
    patch = json.loads(p.read_text())
    assert patch.get('format') == 1 and patch.get('tid') == '01006F8002326000', f'{p}: not qol-peanuts-patch.json'
    patch['rstb'] = rstb_field(Path(a.table))
    p.write_text(json.dumps(patch))
    print(f'{p}: rstb added, {p.stat().st_size} bytes')


if __name__ == '__main__':
    main()
