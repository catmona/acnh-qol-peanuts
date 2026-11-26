/* QoL Enhancements for Peanuts: the engine behind index.html. Also loaded by the Jubbsticks page (same origin).
   Exposes globalThis.QOL and, under Node, module.exports. */
(function () {
'use strict';
const TID = '01006F8002326000';

function lz4(src, outLen) {
  const dst = new Uint8Array(outLen); let s = 0, d = 0;
  while (s < src.length) {
    const tok = src[s++]; let n = tok >> 4, b;
    if (n === 15) do { b = src[s++]; n += b; } while (b === 255);
    dst.set(src.subarray(s, s + n), d); s += n; d += n;
    if (s >= src.length) break;
    const off = src[s] | (src[s + 1] << 8); s += 2;
    n = tok & 15;
    if (n === 15) do { b = src[s++]; n += b; } while (b === 255);
    n += 4;
    if (off === 0 || off > d || d + n > outLen) throw new Error('bad LZ4 data');
    for (let i = 0; i < n; i++, d++) dst[d] = dst[d - off];
  }
  if (d !== outLen) throw new Error('bad LZ4 size');
  return dst;
}

async function readZip(u) {
  const v = new DataView(u.buffer, u.byteOffset, u.byteLength);
  let e = u.length - 22;
  while (e >= 0 && v.getUint32(e, true) !== 0x06054b50) e--;
  if (e < 0) throw new Error('not a zip file');
  const count = v.getUint16(e + 10, true); let c = v.getUint32(e + 16, true);
  const files = new Map(), dec = new TextDecoder();
  for (let k = 0; k < count; k++) {
    if (v.getUint32(c, true) !== 0x02014b50) throw new Error('broken zip directory');
    const method = v.getUint16(c + 10, true), csize = v.getUint32(c + 20, true), usize = v.getUint32(c + 24, true);
    const nlen = v.getUint16(c + 28, true), elen = v.getUint16(c + 30, true), clen = v.getUint16(c + 32, true);
    const lo = v.getUint32(c + 42, true), name = dec.decode(u.subarray(c + 46, c + 46 + nlen));
    c += 46 + nlen + elen + clen;
    if (name.endsWith('/')) continue;
    const at = lo + 30 + v.getUint16(lo + 26, true) + v.getUint16(lo + 28, true), raw = u.subarray(at, at + csize);
    files.set(name, async () => {
      if (method === 0) return raw;
      if (method !== 8) throw new Error(name + ': unsupported compression');
      const out = new Uint8Array(await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer());
      if (out.length !== usize) throw new Error(name + ': bad size');
      return out;
    });
  }
  return files;
}

const CRC = new Uint32Array(256).map((_, n) => { for (let k = 0; k < 8; k++) n = n & 1 ? 0xEDB88320 ^ (n >>> 1) : n >>> 1; return n >>> 0; });
function crc32(u) { let c = 0xFFFFFFFF; for (let i = 0; i < u.length; i++) c = CRC[(c ^ u[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }

function writeZip(entries) {   // [name, bytes], stored (no compression)
  const enc = new TextEncoder(), parts = [], dir = []; let off = 0;
  for (const [name, data] of entries) {
    const n = enc.encode(name), crc = crc32(data), h = new DataView(new ArrayBuffer(30));
    h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x800, true); h.setUint16(12, 0x21, true);
    h.setUint32(14, crc, true); h.setUint32(18, data.length, true); h.setUint32(22, data.length, true); h.setUint16(26, n.length, true);
    const d = new DataView(new ArrayBuffer(46));
    d.setUint32(0, 0x02014b50, true); d.setUint16(4, 20, true); d.setUint16(6, 20, true); d.setUint16(8, 0x800, true); d.setUint16(14, 0x21, true);
    d.setUint32(16, crc, true); d.setUint32(20, data.length, true); d.setUint32(24, data.length, true); d.setUint16(28, n.length, true);
    d.setUint32(42, off, true);
    parts.push(new Uint8Array(h.buffer), n, data); dir.push(new Uint8Array(d.buffer), n);
    off += 30 + n.length + data.length;
  }
  const size = dir.reduce((a, b) => a + b.length, 0), e = new DataView(new ArrayBuffer(22));
  e.setUint32(0, 0x06054b50, true); e.setUint16(8, entries.length, true); e.setUint16(10, entries.length, true);
  e.setUint32(12, size, true); e.setUint32(16, off, true);
  return new Blob([...parts, ...dir, new Uint8Array(e.buffer)], { type: 'application/zip' });
}

const hex = b => Array.from(new Uint8Array(b), x => x.toString(16).padStart(2, '0')).join('');
const sha256 = async u => hex(await crypto.subtle.digest('SHA-256', u));
const unb64 = s => Uint8Array.from(atob(s), ch => ch.charCodeAt(0));

// The size table code (ACNH RSTB Fixer's lib, docs/rstb-lib.js), loaded next to this file the first time a table is made.
// The Jubbsticks page loads this file from the QoL site, so the path comes from this script's own URL.
const HERE = typeof document !== 'undefined' && document.currentScript ? document.currentScript.src : '';
let lib = null;
const rstbLib = () => lib || (lib = typeof module !== 'undefined' ? Promise.resolve(require('./rstb-lib.js'))
  : globalThis.RSTB ? Promise.resolve(globalThis.RSTB)
  : new Promise((res, rej) => {
      const s = document.createElement('script'); s.src = new URL('rstb-lib.js', HERE || location.href).href;
      s.onload = () => res(globalThis.RSTB);
      s.onerror = () => { lib = null; rej(new Error("I couldn't load the size table part of this page. Check your connection.")); };
      document.head.append(s);
    }));

// ResourceSizeTable.srsizetable for the zip. The game refuses a file bigger than its entry, and QoL's layouts are bigger
// than vanilla's (LBellCounterRT needs 472,256 bytes, vanilla allows 77,952). Peanuts takes the table, like every file,
// from the first-installed mod, and QoL goes first, so this one table must also fit the mods installed after it
// ('others': [{ name, bytes }] zips or 7z files, the Jubbsticks zip among them). Base: vanilla 3.0.3's table from the
// patch file, then each mod's own table merged in at the larger size; every romfs file is sized by the fixer's rules,
// entries are only raised, and geometry models in these mods lose their entry so the game sizes them.
async function sizeTable(own, patch, others) {
  const L = await rstbLib(), mods = [{ name: 'QoL Enhancements', files: new Map(own.map(([p, d]) => [p, async () => d])) }];
  for (const x of others) {
    const u = x.bytes;
    try { mods.push({ name: x.name, files: u[0] === 0x37 && u[1] === 0x7A ? await L.read7z(u) : await L.readZip(u) }); }
    catch (e) { throw new Error(`${x.name}: ${e.message}`); }
  }
  let base = null;
  if (patch.rstb) {
    base = unb64(patch.rstb.data);
    if (await sha256(base) !== patch.rstb.sha256) throw new Error('The size table in the patch file came out wrong. Please open an issue.');
  } else if (!mods.some(m => [...m.files.keys()].some(n => L.romfsPath(n) === L.TABLE)))
    return { bytes: null, note: 'No size table: this patch file is older than the page' };
  const r = await L.rebuild(mods, base, d => L.fzstd.decompress(d));
  const n = a => r.rows.filter(x => x.action === a).length, fmt = x => x.toLocaleString('en-US');
  const parts = [`${fmt(n('raised') + n('added'))} sizes raised`, n('removed') && `${fmt(n('removed'))} model entries left to the game`].filter(Boolean);
  return { bytes: r.table, rows: r.rows, notes: r.notes, entries: r.entries,
           note: `Size table: ${parts.join(', ')}` + (others.length ? `, covers ${others.map(x => x.name).join(', ')}` : '') };
}

// o.table: also write the size table (the page's flow asks for it and passes the later mods as o.others). Without it the zip
// has no table, as before: an older flow builds QoL before Jubbsticks, and a QoL table made without the port's sizes would hide them.
async function build(modBytes, patch, o = {}) {
  if (patch.format !== 1 || patch.tid !== TID) throw new Error('That is not the qol-peanuts-patch.json file.');
  const files = await readZip(modBytes);
  const core = [...files.keys()].find(n => n.endsWith(`atmosphere/contents/${TID}/exefs/subsdk6`));
  if (!core) throw new Error('No Core plugin in that zip. Pick the "Modded Switch" download, not the emulator one.');
  const base = core.slice(0, -'exefs/subsdk6'.length);
  const nso = await files.get(core)(), v = new DataView(nso.buffer, nso.byteOffset, nso.byteLength);
  if (hex(nso.subarray(0x40, 0x54)) !== patch.plugin_build_id) throw new Error('This is not QoL Enhancements 1.1.0. The patch only fits 1.1.0.');
  const flags = v.getUint32(0xC, true), segs = [];
  for (let k = 0; k < 3; k++)
    segs.push({ foff: v.getUint32(0x10 + 16 * k, true), moff: v.getUint32(0x14 + 16 * k, true), size: v.getUint32(0x18 + 16 * k, true),
                csize: v.getUint32(0x60 + 4 * k, true), comp: flags & (1 << k) });
  const img = new Uint8Array(Math.max(...segs.map(s => s.moff + s.size)));
  for (const s of segs) {
    const raw = nso.subarray(s.foff, s.foff + s.csize);
    img.set(s.comp ? lz4(raw, s.size) : raw, s.moff);
  }
  if (await sha256(img) !== patch.stock_image_sha256) throw new Error('The Core plugin in that zip is not the stock 1.1.0 file.');
  for (const [off, b] of patch.edits) img.set(unb64(b), off);
  const head = unb64(patch.header), body = segs.map(s => img.subarray(s.moff, s.moff + s.size));
  const sub6 = new Uint8Array(head.length + body.reduce((a, b) => a + b.length, 0));
  let at = 0; for (const p of [head, ...body]) { sub6.set(p, at); at += p.length; }
  if (await sha256(sub6) !== patch.subsdk6_sha256) throw new Error('The patched plugin came out wrong. Please open an issue.');

  const out = `atmosphere/contents/${TID}`, entries = [[`${out}/exefs/subsdk6`, sub6]];
  const npdm = files.get(base + 'exefs/main.npdm');
  if (!npdm) throw new Error('main.npdm is missing from that zip.');
  entries.push([`${out}/exefs/main.npdm`, await npdm()]);
  const romfs = [...files.keys()].filter(n => n.startsWith(base + 'romfs/')).sort();
  for (const n of romfs) entries.push([`${out}/${n.slice(base.length)}`, await files.get(n)()]);
  let table = null;
  if (o.table) {
    table = await sizeTable(entries.filter(([p]) => p.startsWith(`${out}/romfs/`)), patch, o.others || []);
    if (table.bytes) {   // replaces a table the mod shipped (already merged in)
      const at = `${out}/romfs/System/Resource/ResourceSizeTable.srsizetable`, i = entries.findIndex(([p]) => p === at);
      if (i >= 0) entries.splice(i, 1);
      entries.push([at, table.bytes]);
    }
  }
  entries.push([`atmosphere/exefs_patches/qol-peanuts/${patch.ips_name}`, unb64(patch.ips)]);
  return { zip: writeZip(entries), romfs: romfs.length, table };
}


// The memory fix: its own small mod, one IPS for ACNH 3.0.3's main. It makes the game's fixed draw-array heap bigger and
// grows its parent heap by the same amount, out of memory the game leaves unused (tools/make_memfix.py, docs/PORT.md).
const MEMFIX = { name: 'acnh-memory-fix-peanuts.zip', set: 'acnh-memory-fix', build_id: 'ff1d1c05670db6021c85b624a710b963',
                 ips: 'SVBTMzIBVjygAAQAgKBSBATXeAAEAABwJkVFT0Y=' };
const memFixZip = () => writeZip([[`atmosphere/exefs_patches/${MEMFIX.set}/${MEMFIX.build_id}.ips`, unb64(MEMFIX.ips)]]);

// Cheap check used when a file is picked: is this the QoL 1.1.0 "Modded Switch" zip that the patch fits? Throws a friendly message if not.
async function check(modBytes, patch) {
  if (patch.format !== 1 || patch.tid !== TID) throw new Error('That is not the qol-peanuts-patch.json file.');
  const files = await readZip(modBytes);
  const core = [...files.keys()].find(n => n.endsWith(`atmosphere/contents/${TID}/exefs/subsdk6`));
  if (!core) throw new Error('No Core plugin in that zip. Pick the "Modded Switch" download, not the emulator one.');
  const nso = await files.get(core)();
  if (hex(nso.subarray(0x40, 0x54)) !== patch.plugin_build_id) throw new Error('This is not QoL Enhancements 1.1.0. The patch only fits 1.1.0.');
  return 'QoL Enhancements 1.1.0';
}

// What the page calls: one zip out.
const make = async (modBytes, patch, o = {}) => {
  const r = await build(modBytes, patch, o);
  return { zip: r.zip, note: `${r.romfs} files` + (r.table ? `. ${r.table.note}` : '') };
};

const api = { build, check, make, sizeTable, rstbLib, MEMFIX, memFixZip, writeZip, lz4, readZip };
globalThis.QOL = api;
if (typeof module !== 'undefined') module.exports = api;
})();
