/* The shared 3-step flow of the QoL and Jubbsticks pages: get downloads -> pick them -> make and install.
   Kept byte-identical in both repos (acnh-qol-peanuts/docs/flow.js and acnh-jubbsticks-peanuts/docs/flow.js).
   The page sets window.FLOW_SELF ('qol' or 'jub') and has already loaded its own engine (QOL / JUB); the other mod's engine and
   patch come from the other repo's GitHub Pages folder (same origin) and are only fetched once a file for that mod is picked. */
(function () {
'use strict';
const SELF = window.FLOW_SELF, TID = '01006F8002326000';
const MODS = {
  qol: { name: 'QoL Enhancements', global: 'QOL', zip: 'qol-enhancements-peanuts.zip', engine: '/acnh-qol-peanuts/qol.js',
         patchLocal: 'qol-peanuts-patch.json', patchAbs: '/acnh-qol-peanuts/qol-peanuts-patch.json', patchName: 'qol-peanuts-patch.json',
         patchPage: 'https://github.com/catmona/acnh-qol-peanuts/releases/latest',
         get: `<b>QoL Enhancements</b>: on <a href="https://gamebanana.com/mods/727637" target="_blank" rel="noopener">GameBanana</a>
               get <b>Main download (Modded Switch)</b> (<code>qol-switch-v1_1_0-acnh-v3_0_3.zip</code>). Don't unzip it.`,
         want: 'Want QoL Enhancements too?' },
  jub: { name: "Jubbsticks' Additions", global: 'JUB', zip: 'jubbsticks-additions-peanuts.zip', engine: '/acnh-jubbsticks-peanuts/engine.js',
         patchLocal: 'jub-port-patch.json', patchAbs: '/acnh-jubbsticks-peanuts/jub-port-patch.json', patchName: 'jub-port-patch.json',
         patchPage: 'https://github.com/catmona/acnh-jubbsticks-peanuts/releases/latest',
         get: `<b>Jubbsticks' Additions port</b>: on the port's <a href="https://github.com/dragonloverlord/Unnofficial-Jubbsticks-Additions-Port/releases" target="_blank" rel="noopener">Releases page</a>
               get <code>UJAP-BetaRelease-V002-Atmosphere.7z</code>. Read the rules in its README first, and don't extract the file.`,
         want: "Want Jubbsticks' Additions too?" },
};
const OTHER = SELF === 'qol' ? 'jub' : 'qol', ORDER = ['qol', 'jub'];   // install order

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
  details.others { margin-top: 12px; padding: 8px 14px; border-radius: 16px; border: 2px dashed var(--line); }
  details.others summary { cursor: pointer; font: 600 1rem Fredoka, Nunito, sans-serif; }
  details.others p { margin: 8px 0 0; font-size: .95rem; }
  .out { list-style: none; counter-reset: o; margin: 10px 0 0; padding: 0; display: grid; gap: 10px; }
  .out li { counter-increment: o; display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: center; }
  .out li::before { content: counter(o); width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
                    background: var(--leaf); color: #fff; font: 600 1rem Fredoka, sans-serif; }
  .out li.more::before { background: var(--bark-soft); }
  .out small { display: block; color: var(--bark-soft); font-weight: 500; }
  .out b { overflow-wrap: anywhere; }
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
const mb = n => (n / 1048576).toFixed(1) + ' MB';

// ---- markup
const getBlock = (k, opt) => opt
  ? `<div class="dl opt"><p class="want">${MODS[k].want} <span style="font-weight:500">(optional)</span></p><p>${MODS[k].get}</p></div>`
  : `<div class="dl"><p>${MODS[k].get}</p></div>`;
const patchBox = k => `<div class="patchbox" id="pb-${k}" hidden>
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
        <details class="others" id="others-box" hidden>
          <summary>Using other mods too (like ACNH Combined)?</summary>
          <p>Pick their .zip or .7z files here, so the size table also covers the sizes they raised. Install the zips from this page
            <b>before</b> your other mods: Peanuts uses the first-installed mod's copy of a file and has no reorder, so reinstall the others after.</p>
          <label class="pick"><input class="sr" type="file" id="others" accept=".7z,.zip" multiple>
            <span class="pill">Pick other mods</span><span class="fname" id="others-name">None</span></label>
        </details>
      </div>
    </li>
    <li class="card step" id="step-3">
      <span class="num" aria-hidden="true">3</span>
      <div>
        <h2>Make and install</h2>
        <label class="fixopt"><input type="checkbox" id="fix" checked>
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
    <p style="margin-top:14px">In Peanuts, long-press ACNH, choose <b>Install mod&hellip; &gt; Zip file</b> and add each zip in that order.
      Peanuts then rebuilds the game, which takes about 5 minutes.</p>
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
const patchOf = k => patches[k] || (patches[k] = (async () => {
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
const render = () => {
  $('rows').innerHTML = rows.map(r => `<li class="row ${r.cls}">${r.cls === 'ok' ? '&#10003; ' : r.cls === 'bad' ? '&#10007; ' : ''}${esc(r.text)}<small>${esc(r.sub)}</small></li>`).join('');
  $('step-2').classList.toggle('done', !!Object.keys(picked).length);
  $('go').disabled = !Object.keys(picked).length || !!$('go').dataset.busy;
  $('others-box').hidden = !picked.jub;
  $('files-pill').textContent = Object.keys(picked).length ? 'Pick more' : 'Pick downloads';
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
$('others').onchange = () => { const f = [...$('others').files]; $('others-name').textContent = f.length ? f.map(x => x.name).join(', ') : 'None'; };

// ---- make everything
$('go').onclick = async () => {
  $('go').dataset.busy = '1'; render(); $('results').hidden = true;
  const outs = [], fix = $('fix').checked;
  try {
    for (const k of ORDER) {
      if (!picked[k]) continue;
      status(`Making ${MODS[k].zip}…`); await tick();
      const [eng, patch] = await Promise.all([engineOf(k), patchOf(k)]);
      const others = [];
      if (k === 'jub') for (const f of $('others').files) others.push({ name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) });
      const r = await eng.make(new Uint8Array(await picked[k].file.arrayBuffer()), patch, { fix, others });
      outs.push({ name: MODS[k].zip, blob: r.zip, note: r.note });
    }
    if (fix) { const own = window[MODS[SELF].global]; outs.push({ name: own.MEMFIX.name, blob: own.memFixZip(), note: 'Gives the game more room for item pictures.' }); }
    $('out').innerHTML = outs.map((o, i) => `<li><span><b>${esc(o.name)}</b><small>${mb(o.blob.size)}. ${esc(o.note)}</small></span>
        <button class="dlb" data-i="${i}">Download</button></li>`).join('') + '<li class="more"><span><b>Then any other mods you use</b></span></li>';
    for (const b of $('out').querySelectorAll('.dlb')) b.onclick = () => save(outs[b.dataset.i].blob, outs[b.dataset.i].name);
    $('jub-note').hidden = !picked.jub; $('results').hidden = false;
    outs.forEach((o, i) => setTimeout(() => save(o.blob, o.name), i * 400));
    status(`Done. ${outs.length} zip${outs.length > 1 ? 's' : ''} made. Install them in the order below.`, 'ok');
    $('results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) { status(e.message, 'err'); }
  delete $('go').dataset.busy; render();
};

patchOf(SELF);   // fetch our own patch now, so a missing one shows its fallback picker straight away
render();
})();
