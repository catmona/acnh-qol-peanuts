// Checks the size table the patcher page writes, with the page's own code (docs/qol.js, docs/rstb-lib.js).
//
//   node tools/check_rstb.mjs <qol-switch-v1_1_0-acnh-v3_0_3.zip> [--patch docs/qol-peanuts-patch.json]
//        [--vanilla <3.0.3 ResourceSizeTable.srsizetable>] [--write <out.zip>] [later mod .zip/.7z ...]
//
// It builds the QoL zip as the page does (the later mods are what the page passes: the Jubbsticks zip it made, then the
// other mods), reads the table back out of that zip, and fails if:
//   - a romfs file in the QoL zip or a later mod needs more than its entry (by the fixer's rules), or has no entry
//     where a rule gives a size;
//   - a geometry model in those mods still has an entry (the game must size it);
//   - an entry is smaller than in vanilla (--vanilla) or in a later mod's own table, other than a removed model.
// Every copy of a file is checked, not just the one Peanuts uses (the first-installed), so the order cannot hide a miss.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const QOL = require('../docs/qol.js'), R = require('../docs/rstb-lib.js');

const a = process.argv.slice(2), later = [];
let qol = null, patchPath = path.join(import.meta.dirname, '../docs/qol-peanuts-patch.json'), vanilla = null, write = null;
for (let i = 0; i < a.length; i++) {
  if (a[i] === '--patch') patchPath = a[++i]; else if (a[i] === '--vanilla') vanilla = a[++i]; else if (a[i] === '--write') write = a[++i];
  else if (!qol) qol = a[i]; else later.push(a[i]);
}
if (!qol) { console.error('usage: check_rstb.mjs <qol zip> [--patch <json>] [--vanilla <table>] [--write <zip>] [later mods...]'); process.exit(2); }

const patch = JSON.parse(fs.readFileSync(patchPath, 'utf8'));
const others = later.map(p => ({ name: path.basename(p), bytes: new Uint8Array(fs.readFileSync(p)) }));
const t0 = Date.now();
const r = await QOL.build(new Uint8Array(fs.readFileSync(qol)), patch, { table: true, others });
const ms = Date.now() - t0;
const zip = new Uint8Array(await r.zip.arrayBuffer());
if (write) fs.writeFileSync(write, zip);
console.log(`built in ${ms} ms, ${zip.length} bytes. ${r.table.note}`);
for (const n of r.table.notes || []) console.log('  ' + n);

const outFiles = await R.readZip(zip), TID = '01006F8002326000';
const tables = [...outFiles.keys()].filter(n => R.romfsPath(n) === R.TABLE);
if (!r.table.bytes) { console.log(tables.length ? 'FAIL: a table is in the zip but the build said none' : 'no table written (as the note says)'); process.exit(tables.length ? 1 : 0); }
if (tables.length !== 1 || tables[0] !== `atmosphere/contents/${TID}/romfs/${R.TABLE}`) { console.log('FAIL: tables in the zip:', tables); process.exit(1); }
const T = R.tableParse(await outFiles.get(tables[0])());

const sets = [{ name: 'QoL zip', files: outFiles }];
for (const o of others) sets.push({ name: o.name, files: o.bytes[0] === 0x37 && o.bytes[1] === 0x7A ? await R.read7z(o.bytes) : await R.readZip(o.bytes) });
const fails = [], removed = new Set(), modTables = [], stat = { sized: 0, removed: 0, noRule: 0 };
const crc = p => R.crc32(new TextEncoder().encode(p));
for (const s of sets) for (const [name, get] of s.files) {
  let p = R.romfsPath(name); if (!p) continue;
  if (p === R.TABLE) { if (s.files !== outFiles) modTables.push({ name: s.name, T: R.tableParse(await get()) }); continue; }
  let d = await get(); if (p.endsWith('.zs')) { p = p.slice(0, -3); d = R.fzstd.decompress(d); }
  const want = R.sizeFor(p, d), e = R.tableGet(T, p);
  if (!want) { stat.noRule++; continue; }
  if (want.remove) { stat.removed++; removed.add(p); if (e) fails.push(`${s.name}: ${p} is a geometry model but has an entry (${e[0]})`); continue; }
  stat.sized++;
  if (!e) fails.push(`${s.name}: ${p} needs ${want.size} and has no entry`);
  else if (e[0] < want.size) fails.push(`${s.name}: ${p} needs ${want.size}, entry is ${e[0]}`);
}
const removedKeys = new Set([...removed].map(crc));
const lowered = (name, B) => {
  let n = 0;
  for (const [k, e] of B.hashed) { if (removedKeys.has(k)) continue; const o = T.hashed.get(k); if (!o || o[0] < e[0]) { n++; if (n <= 10) fails.push(`${name}: entry ${k.toString(16)} is ${o ? o[0] : 'gone'}, was ${e[0]}`); } }
  for (const [k, e] of B.named) { if (removed.has(k)) continue; const o = T.named.get(k); if (!o || o[0] < e[0]) { n++; if (n <= 10) fails.push(`${name}: entry ${k} is ${o ? o[0] : 'gone'}, was ${e[0]}`); } }
  return n;
};
const checks = [...modTables];
if (vanilla) checks.unshift({ name: 'vanilla', T: R.tableParse(fs.readFileSync(vanilla)) });
for (const c of checks) { const n = lowered(c.name, c.T); console.log(`vs ${c.name}'s table (${c.T.hashed.size + c.T.named.size} entries): ${n} lowered or dropped, removed models aside`); }
console.log(`table: ${T.magic}, ${T.hashed.size + T.named.size} entries. Files: ${stat.sized} sized and fit, ${stat.removed} geometry models without an entry, ${stat.noRule} with no rule (no entries for their kind)`);
if (fails.length) { console.log(`FAIL (${fails.length}):`); for (const f of fails.slice(0, 40)) console.log('  ' + f); process.exit(1); }
console.log('OK: every file fits its entry');
