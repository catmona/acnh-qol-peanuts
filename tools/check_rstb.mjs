// Checks the size table mod the patcher page makes, with the page's own code: docs/qol.js for the QoL zip, then ACNH RSTB
// Fixer from the docs/rstb submodule (the lib the page loads through rstb/lib/page.js), called as docs/flow.js calls it.
//
//   node tools/check_rstb.mjs <qol-switch-v1_1_0-acnh-v3_0_3.zip> [--patch docs/qol-peanuts-patch.json]
//        [--vanilla <3.0.3 ResourceSizeTable.srsizetable>] [--write <out dir>] [later mod .zip/.7z/folder ...]
//
// The later mods are what the page gets: the Jubbsticks zip it made, then the other mods. It builds the QoL zip, makes the
// table mod over [QoL zip, later mods] with vanilla's table from the patch file as the base (buildTableMod('peanuts', ...)),
// and fails (checkFit) if:
//   - any copy of a romfs file in those mods needs more than its entry, or has no entry where a rule gives a size
//     (every copy, not just the one Peanuts uses, so the install order can't hide a miss);
//   - a geometry model in those mods still has an entry (the game must size it);
//   - an entry is smaller than in vanilla (--vanilla, else the patch file's table) or in a mod's own table, removed models aside.
// It also fails if the QoL zip has a table of its own: the page installs the table mod first, and the zips carry none.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const lib = p => require(path.join(import.meta.dirname, '../docs/rstb', p));
if (!fs.existsSync(path.join(import.meta.dirname, '../docs/rstb/lib/mods.js'))) { console.error('docs/rstb is empty: run git submodule update --init'); process.exit(2); }
const QOL = require('../docs/qol.js'), F = lib('lib/formats.js'), R = lib('lib/rstb.js'), M = lib('lib/mods.js'), fzstd = lib('vendor/fzstd.umd.js');

const a = process.argv.slice(2), later = [];
let qol = null, patchPath = path.join(import.meta.dirname, '../docs/qol-peanuts-patch.json'), vanilla = null, write = null;
for (let i = 0; i < a.length; i++) {
  if (a[i] === '--patch') patchPath = a[++i]; else if (a[i] === '--vanilla') vanilla = a[++i]; else if (a[i] === '--write') write = a[++i];
  else if (!qol) qol = a[i]; else later.push(a[i]);
}
if (!qol) { console.error('usage: check_rstb.mjs <qol zip> [--patch <json>] [--vanilla <table>] [--write <dir>] [later mods...]'); process.exit(2); }

const patch = JSON.parse(fs.readFileSync(patchPath, 'utf8'));
const t0 = Date.now();
const built = await QOL.make(new Uint8Array(fs.readFileSync(qol)), patch, {});
const qolZip = new Uint8Array(await built.zip.arrayBuffer());
const mods = [await M.readMod('qol-enhancements-peanuts.zip', qolZip)];
if ([...mods[0].files.keys()].some(n => R.romfsPath(n) === R.TABLE)) { console.log('FAIL: the QoL zip has a size table of its own'); process.exit(1); }
const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]);
for (const p of later) {
  if (fs.statSync(p).isDirectory()) {
    const r = await M.folderMods(path.basename(p), walk(p).map(f => [path.relative(p, f).split(path.sep).join('/'), async () => fs.readFileSync(f)]));
    for (const n of r.notes) console.log('  ' + n);
    mods.push(...r.mods);
  } else mods.push(await M.readMod(path.basename(p), new Uint8Array(fs.readFileSync(p))));
}
const base = await QOL.baseTable(patch);
if (!base) console.log("the patch file has no vanilla table: the mods' own tables are the base");
const t = await M.buildTableMod('peanuts', mods, base, d => fzstd.decompress(d));
const ms = Date.now() - t0;
const tableZip = new Uint8Array(await F.writeZip(t.mod.entries).arrayBuffer());
if (write) {
  fs.mkdirSync(write, { recursive: true });
  fs.writeFileSync(path.join(write, 'qol-enhancements-peanuts.zip'), qolZip);
  fs.writeFileSync(path.join(write, t.mod.name), tableZip);
}
console.log(`QoL zip ${qolZip.length} bytes (${built.note}); ${t.mod.name} ${tableZip.length} bytes, ${t.entries} entries, ${ms} ms`);
console.log('  ' + t.summary);
for (const n of t.notes) console.log('  ' + n);

// Read the table back out of the zip, as the game would get it.
const out = await F.readZip(tableZip), keys = [...out.keys()];
if (keys.length !== 1 || keys[0] !== `atmosphere/contents/${M.TID}/romfs/${R.TABLE}`) { console.log('FAIL: files in the table mod:', keys); process.exit(1); }
const against = [{ name: 'vanilla', table: vanilla ? fs.readFileSync(vanilla) : base }].filter(x => x.table);
const r = await R.checkFit(await out.get(keys[0])(), mods, d => fzstd.decompress(d), against);
for (const l of r.lowered) console.log(`vs ${l.name}'s table (${l.entries} entries): ${l.n} lowered or dropped, removed models aside`);
console.log(`table ${r.magic}, ${r.entries} entries. Files: ${r.sized} sized, ${r.removed} geometry models without an entry, ${r.noRule} with no rule (no entries for their kind)`);
if (r.fails.length) { console.log(`FAIL (${r.fails.length}):`); for (const f of r.fails.slice(0, 40)) console.log('  ' + f); process.exit(1); }
console.log('OK: every file fits its entry');
