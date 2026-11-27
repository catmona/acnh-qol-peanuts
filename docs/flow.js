/* The shared 3-step flow of the QoL and Jubbsticks pages: get downloads -> pick them -> make and install.
   Kept byte-identical in both repos (acnh-qol-peanuts/docs/flow.js and acnh-jubbsticks-peanuts/docs/flow.js).
   The page sets window.FLOW_SELF ('qol' or 'jub') and has already loaded its own engine (QOL / JUB); the other mod's engine and
   patch come from the other repo's GitHub Pages folder (same origin) and are only fetched once a file for that mod is picked.
   A mod whose patchLocal is null has no patch file: nothing is fetched and its engine gets null.
   The size table comes from ACNH RSTB Fixer, the docs/rstb submodule of each repo (rstb/lib/page.js next to the page): one
   table, made as its own small mod over every mod the player picks, installed first. */
(function () {
'use strict';
const SELF = window.FLOW_SELF, TID = '01006F8002326000';
const FIXER = 'https://catmona.github.io/acnh-rstb-fixer/';
const MODS = {
  qol: { name: 'QoL Enhancements', global: 'QOL', zip: 'qol-enhancements-peanuts.zip', engine: '/acnh-qol-peanuts/qol.js',
         patchLocal: 'qol-peanuts-patch.json', patchAbs: '/acnh-qol-peanuts/qol-peanuts-patch.json', patchName: 'qol-peanuts-patch.json',
         patchPage: 'https://github.com/catmona/acnh-qol-peanuts/releases/latest',
         get: `<b>QoL Enhancements</b>: on <a href="https://gamebanana.com/mods/727637" target="_blank" rel="noopener">GameBanana</a>
               get <b>Main download (Modded Switch)</b> (<code>qol-switch-v1_1_0-acnh-v3_0_3.zip</code>). Don't unzip it.`,
         want: 'Want QoL Enhancements too?' },
  jub: { name: "Jubbsticks' Additions", global: 'JUB', zip: 'jubbsticks-additions-peanuts.zip', engine: '/acnh-jubbsticks-peanuts/engine.js',
         patchLocal: null, patchAbs: null, patchName: null, patchPage: null,   // the Jubbsticks engine needs no patch file
         get: `<b>Jubbsticks' Additions port</b>: on the port's <a href="https://github.com/dragonloverlord/Unnofficial-Jubbsticks-Additions-Port/releases" target="_blank" rel="noopener">Releases page</a>
               get the latest Atmosphere <code>.7z</code>. Read the rules in its README first, and don't extract the file.`,
         want: "Want Jubbsticks' Additions too?" },
};
const OTHER = SELF === 'qol' ? 'jub' : 'qol', ORDER = ['qol', 'jub'];   // install order, after the size table

const css = document.createElement('style');
css.textContent = `
  .dl { margin: 10px 0 0; padding: 10px 14px; border-radius: 16px; background: #fff; border: 2px solid var(--line); }
  .dl p { margin: 0; }
  .dl.opt { background: transparent; border-style: dashed; }
  .dl .want { font: 600 1rem Fredoka, Nunito, sans-serif; margin-bottom: 4px; }
  .rows { list-style: none; margin: 10px 0 0; padding: 0; display: grid; gap: 6px; }
  .row { padding: 8px 12px; border-radius: 14px; background: #fff; border: 2px solid var(--line); font-weight: 800; overflow-wrap: anywhere; }
  .row small { display: block; font-weight: 500; color: var(--bark-soft); }
  .row.ok { border-color: var(--leaf); color: var(--ok); }
  .row.bad { border-color: var(--err); color: var(--err); }
  .patchbox { margin-top: 10px; padding: 10px 14px; border-radius: 16px; background: var(--cream-2); }
  .others { margin-top: 12px; padding: 8px 14px 12px; border-radius: 16px; border: 2px dashed var(--line); }
  .others .want { font: 600 1rem Fredoka, Nunito, sans-serif; margin: 0; }
  .others p { margin: 8px 0 0; font-size: .95rem; }
  .others .picks { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; align-items: center; }
  .others .picks .pick { margin: 0; }
  .linkish { background: none; border: 0; padding: 0; margin: 0; width: auto; color: var(--bark-soft); text-decoration: underline; font: inherit; cursor: pointer; }
  .out { list-style: none; counter-reset: o; margin: 10px 0 0; padding: 0; display: grid; gap: 10px; }
  .out li { counter-increment: o; display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: center; }
  .out li::before { content: counter(o); width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
                    background: var(--leaf); color: #fff; font: 600 1rem Fredoka, sans-serif; }
  .out li.more::before { background: var(--bark-soft); }
  .out small { display: block; color: var(--bark-soft); font-weight: 500; }
  .out b { overflow-wrap: anywhere; }
  .out ol.how { margin: 6px 0 0; padding-left: 1.2em; font-size: .92rem; font-weight: 500; }
  .dlb { width: auto; margin: 0; padding: 8px 16px; font-size: 1rem; }
  #results { margin-top: 18px; }
  #results h2 { margin-top: 0; }
`;
document.head.append(css);

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const tick = () => new Promise(r => setTimeout(r, 30));
const save = (blob, name) => {
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove();
};
const mb = n => n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
// A folder picker only where the browser has one and it's a computer: phones open a file picker without folders.
const canDir = 'webkitdirectory' in document.createElement('input') && !/Android|iPhone|iPad|iPod|Mobi/i.test(navigator.userAgent);

// ---- markup
const getBlock = (k, opt) => opt
  ? `<div class="dl opt"><p class="want">${MODS[k].want} <span style="font-weight:500">(optional)</span></p><p>${MODS[k].get}</p></div>`
  : `<div class="dl"><p>${MODS[k].get}</p></div>`;
const patchBox = k => !MODS[k].patchLocal ? '' : `<div class="patchbox" id="pb-${k}" hidden>
    <p>I couldn't fetch the ${MODS[k].name} patch by myself (are you opening this page from a file?). Download
      <code>${MODS[k].patchName}</code> from the <a href="${MODS[k].patchPage}" target="_blank" rel="noopener">latest release</a> and pick it here:</p>
    <label class="pick"><input class="sr" type="file" id="pf-${k}" accept=".json,application/json">
      <span class="pill">Pick the patch file</span><span class="fname" id="pfn-${k}"></span></label></div>`;

$('flow').innerHTML = `
  <ol class="steps">
    <li class="card step" id="step-1">
      <span class="num" aria-hidden="true">1</span>
      <div>
        <h2>Get your downloads</h2>
        <p>Download the original file from its own page. Keep it as it is: don't unzip or extract it.</p>
        ${getBlock(SELF, false)}
        ${getBlock(OTHER, true)}
      </div>
    </li>
    <li class="card step" id="step-2">
      <span class="num" aria-hidden="true">2</span>
      <div>
        <h2>Pick your downloads</h2>
        <p>Pick ${SELF === 'qol' ? 'the QoL zip, and the port file too if you got it' : 'the port file, and the QoL zip too if you got it'}.
          You can choose both at once. I'll see which is which.</p>
        <label class="pick"><input class="sr" type="file" id="files" accept=".zip,.7z" multiple>
          <span class="pill" id="files-pill">Pick downloads</span></label>
        <ul class="rows" id="rows" aria-live="polite"></ul>
        ${patchBox(SELF)}${patchBox(OTHER)}
        <div class="others" id="others-box">
          <p class="want">Using other mods that change game files, like ACNH Combined?</p>
          <p>Add them here too. The game uses only one size table, so this page makes it as its own small mod that covers
            every mod you add here. A mod it doesn't cover can crash the game. Make it again after you change your mods.</p>
          <div class="picks">
            <label class="pick"><input class="sr" type="file" id="others" accept=".7z,.zip" multiple>
              <span class="pill">Add mod files (.zip, .7z)</span></label>
            ${canDir ? `<label class="pick"><input class="sr" type="file" id="others-dir" webkitdirectory>
              <span class="pill">Add a mods folder (on a PC)</span></label>` : ''}
          </div>
          <p><span id="others-name">None added.</span> <button class="linkish" id="others-clear" hidden>Clear</button></p>
          <p>Playing on a Switch, or another emulator (Eden, Citron, Ryujinx)? This page lays the table out for Peanuts.
            Make yours on <a href="${FIXER}" target="_blank" rel="noopener">ACNH RSTB Fixer</a>.</p>
        </div>
      </div>
    </li>
    <li class="card step" id="step-3">
      <span class="num" aria-hidden="true">3</span>
      <div>
        <h2>Make and install</h2>
        <label class="fixopt" id="fix-opt"><input type="checkbox" id="fix" checked>
          <span><b>Also make the memory fix</b> (recommended). It's a tiny extra mod that gives the game more room for item pictures,
            so big mods like Jubbsticks' Additions don't crash it or lose their icons.</span></label>
        <button id="go" disabled>Make my Peanuts zips</button>
      </div>
    </li>
  </ol>
  <div class="card dialog" role="status" aria-live="polite">
    <span class="tag">Status</span>
    <p id="status">Pick your download to begin.</p>
  </div>
  <section class="card" id="results" hidden>
    <h2>Install these in Peanuts, in this order</h2>
    <p>They should have downloaded by themselves. If one didn't, use its button.</p>
    <ol class="out" id="out"></ol>
    <p style="margin-top:14px">In Peanuts, long-press ACNH, choose <b>Mods &amp; Cheats &gt; Add &gt; A file</b> and add each zip in that order.
      Peanuts then rebuilds the game, which takes about 5 minutes.</p>
    <p id="table-note" hidden></p>
    <p id="jub-note" hidden>Jubbsticks' Additions adds items, so back up your save first. Start a new game after.</p>
  </section>`;

// ---- engines and patches (the other mod's come from the other repo's Pages folder)
const engineOf = async k => {
  const m = MODS[k];
  if (!window[m.global]) await new Promise((res, rej) => {
    const s = document.createElement('script'); s.src = m.engine; s.onload = res;
    s.onerror = () => rej(new Error(`I couldn't load the ${m.name} part of this page. Check your connection. (This also happens if the page is opened from a file instead of the web.)`));
    document.head.append(s);
  });
  return window[m.global];
};
const patches = {};
const patchOf = k => patches[k] || (patches[k] = !MODS[k].patchLocal ? Promise.resolve(null) : (async () => {
  try {
    const r = await fetch(k === SELF ? MODS[k].patchLocal : MODS[k].patchAbs, { cache: 'no-cache' });
    if (!r.ok) throw new Error('http ' + r.status);
    return await r.json();
  } catch {
    $('pb-' + k).hidden = false;
    return new Promise(res => { $('pf-' + k).onchange = async () => {
      const f = $('pf-' + k).files[0]; if (!f) return;
      let j; try { j = JSON.parse(await f.text()); } catch { $('pfn-' + k).textContent = 'That is not a JSON file.'; return; }
      $('pfn-' + k).textContent = f.name; patches[k] = Promise.resolve(j); res(j);
    }; });
  }
})());

// ---- the size table code (ACNH RSTB Fixer, this page's rstb/ folder)
let rstbReady = null;
const rstb = () => rstbReady || (rstbReady = (async () => {
  if (!(self.ACNH_RSTB && self.ACNH_RSTB.load)) await new Promise((res, rej) => {
    const s = document.createElement('script'); s.src = new URL('rstb/lib/page.js', location.href).href; s.onload = res;
    s.onerror = () => { s.remove(); rej(new Error("I couldn't load the size table part of this page. Check your connection.")); };
    document.head.append(s);
  });
  return self.ACNH_RSTB.load();
})().catch(e => { rstbReady = null; throw e; }));

// ---- telling the downloads apart by what is inside
const zipNames = u => {
  const v = new DataView(u.buffer, u.byteOffset, u.byteLength); let e = u.length - 22;
  while (e >= 0 && e > u.length - 70000 && v.getUint32(e, true) !== 0x06054b50) e--;
  if (e < 0 || v.getUint32(e, true) !== 0x06054b50) return null;
  const n = v.getUint16(e + 10, true), dec = new TextDecoder(), out = []; let c = v.getUint32(e + 16, true);
  for (let i = 0; i < n && c + 46 <= u.length && v.getUint32(c, true) === 0x02014b50; i++) {
    const nl = v.getUint16(c + 28, true), el = v.getUint16(c + 30, true), cl = v.getUint16(c + 32, true);
    out.push(dec.decode(u.subarray(c + 46, c + 46 + nl))); c += 46 + nl + el + cl;
  }
  return out;
};
const is7z = u => u[0] === 0x37 && u[1] === 0x7A && u[2] === 0xBC && u[3] === 0xAF && u[4] === 0x27 && u[5] === 0x1C;
const sniff = u => {
  if (is7z(u)) return 'jub';
  const names = u[0] === 0x50 && u[1] === 0x4B ? zipNames(u) : null;
  if (names) {
    if (names.some(n => n.endsWith(`atmosphere/contents/${TID}/exefs/subsdk6`))) return 'qol';
    if (names.some(n => n.endsWith('romfs/Bcsv/ItemParam.bcsv'))) return 'jub';
  }
  throw new Error("I don't know this file. I need the QoL zip (Main download, Modded Switch) or the port's .7z. Keep them zipped.");
};

// ---- the picker
const picked = {}, rows = []; let seq = 0;
const others = [];   // { name, file } archives and { name, dir: [File] } folders, in the order added
const render = () => {
  $('rows').innerHTML = rows.map(r => `<li class="row ${r.cls}">${r.cls === 'ok' ? '&#10003; ' : r.cls === 'bad' ? '&#10007; ' : ''}${esc(r.text)}<small>${esc(r.sub)}</small></li>`).join('');
  $('step-2').classList.toggle('done', !!Object.keys(picked).length);
  $('go').disabled = !Object.keys(picked).length || !!$('go').dataset.busy;
  $('fix-opt').hidden = !!picked.jub;   // the memory fix always goes out with Jubbsticks' Additions
  $('files-pill').textContent = Object.keys(picked).length ? 'Pick more' : 'Pick downloads';
  $('others-name').textContent = others.length ? others.map(o => o.dir ? o.name + ' (folder)' : o.name).join(', ') : 'None added.';
  $('others-clear').hidden = !others.length;
};
const status = (t, cls) => { $('status').textContent = t; $('status').className = cls || ''; };

$('files').onchange = async () => {
  const list = [...$('files').files]; $('files').value = '';
  if (!list.length) return;
  for (let i = rows.length - 1; i >= 0; i--) if (rows[i].cls !== 'ok') rows.splice(i, 1);
  for (const f of list) {
    const row = { cls: 'wait', text: 'Looking at it…', sub: f.name, id: ++seq }; rows.push(row); render();
    try {
      const u = new Uint8Array(await f.arrayBuffer()), k = sniff(u);
      row.text = `Checking it's ${MODS[k].name}…`; render();
      const [eng, patch] = await Promise.all([engineOf(k), patchOf(k)]);
      row.text = await eng.check(u, patch);
      if (picked[k]) { const old = rows.findIndex(r => r.id === picked[k].row); if (old >= 0) rows.splice(old, 1); }
      picked[k] = { file: f, row: row.id }; row.cls = 'ok';
    } catch (e) { row.cls = 'bad'; row.text = e.message; }
    render();
  }
  status(Object.keys(picked).length ? 'Ready. Press "Make my Peanuts zips".' : 'Pick your download to begin.');
};
const addOther = o => { const i = others.findIndex(x => x.name === o.name); if (i >= 0) others.splice(i, 1); others.push(o); render(); };
$('others').onchange = () => { for (const f of $('others').files) addOther({ name: f.name, file: f }); $('others').value = ''; };
if (canDir) $('others-dir').onchange = () => {
  const fs = [...$('others-dir').files]; $('others-dir').value = ''; if (!fs.length) return;
  addOther({ name: fs[0].webkitRelativePath.split('/')[0], dir: fs });
};
$('others-clear').onclick = () => { others.length = 0; render(); };

// ---- make everything
$('go').onclick = async () => {
  $('go').dataset.busy = '1'; render(); $('results').hidden = true;
  const outs = [], made = {}, fix = !!picked.jub || $('fix').checked;
  let tableNote = '';
  try {
    for (const k of ORDER) {
      if (!picked[k]) continue;
      status(`Making ${MODS[k].zip}…`); await tick();
      const [eng, patch] = await Promise.all([engineOf(k), patchOf(k)]);
      made[k] = await eng.make(new Uint8Array(await picked[k].file.arrayBuffer()), patch, {});
    }
    // One size table over everything the player uses, as its own mod that goes first.
    status('Making the size table…'); await tick();
    const R = await rstb(), mods = [], notes = [];
    const read = (name, bytes) => R.readMod(name, bytes).catch(e => { throw new Error(e.message.startsWith(name) ? e.message : `${name}: ${e.message}`); });
    for (const k of ORDER) if (made[k]) mods.push(await read(MODS[k].zip, new Uint8Array(await made[k].zip.arrayBuffer())));
    for (const o of others) {
      if (o.file) { mods.push(await read(o.name, new Uint8Array(await o.file.arrayBuffer()))); continue; }
      const r = await R.folderMods(o.name, o.dir.map(f => [f.webkitRelativePath.split('/').slice(1).join('/'), () => f.arrayBuffer().then(b => new Uint8Array(b))]));
      mods.push(...r.mods); notes.push(...r.notes);
    }
    // Base: vanilla's table from the QoL patch file. Without QoL, the mods' own tables (the Jubbsticks zip has one).
    const q = picked.qol && await engineOf('qol'), base = q && q.baseTable ? await q.baseTable(await patchOf('qol')) : null;
    try {
      const t = await R.buildTableMod('peanuts', mods, base, d => R.fzstd.decompress(d));
      outs.push({ name: t.mod.name, blob: R.writeZip(t.mod.entries), note: 'Size table. ' + t.summary, steps: t.mod.steps });
      if (notes.length) tableNote = notes.join(' ');
    } catch (e) { tableNote = `No size table was made: ${e.message} Install the zips below without one, or make it on ACNH RSTB Fixer.`; }
    for (const k of ORDER) if (made[k]) outs.push({ name: MODS[k].zip, blob: made[k].zip, note: made[k].note });
    if (fix) { const own = window[MODS[SELF].global]; outs.push({ name: own.MEMFIX.name, blob: own.memFixZip(), note: 'Gives the game more room for item pictures.' }); }
    $('out').innerHTML = outs.map((o, i) => `<li><span><b>${esc(o.name)}</b><small>${mb(o.blob.size)}. ${esc(o.note)}</small>
        ${o.steps ? `<ol class="how">${o.steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}</span>
        <button class="dlb" data-i="${i}">Download</button></li>`).join('') + '<li class="more"><span><b>Then any other mods you use</b></span></li>';
    for (const b of $('out').querySelectorAll('.dlb')) b.onclick = () => save(outs[b.dataset.i].blob, outs[b.dataset.i].name);
    $('table-note').textContent = tableNote; $('table-note').hidden = !tableNote;
    $('jub-note').hidden = !picked.jub; $('results').hidden = false;
    outs.forEach((o, i) => setTimeout(() => save(o.blob, o.name), i * 400));
    status(`Done. ${outs.length} zip${outs.length > 1 ? 's' : ''} made. Install them in the order below.`, 'ok');
    $('results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) { status(e.message, 'err'); }
  delete $('go').dataset.busy; render();
};

patchOf(SELF);   // fetch our own patch now, so a missing one shows its fallback picker straight away
rstb().catch(() => {});   // and start loading the size table code; a failure shows when the zips are made
render();
})();
