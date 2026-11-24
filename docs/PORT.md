# Port notes

State as of 11-23. Build: ACNH 3.0.3, main build ID ff1d1c05670db6021c85b624a710b963.

## Hook inventory

The Core module (`exefs/subsdk6`, exlaunch) installs every feature through one hook-plan function (plugin
offset 0xfd60). It is called from 37 places. Each call passes an array of 0x30-byte requests, laid out as:

| Offset | Field |
| --- | --- |
| +0 | name |
| +8 | callback |
| +0x10 | main offset |
| +0x18 | 16 expected bytes (a fingerprint) |
| +0x28 | u32 |
| +0x2c | enabled byte |

`tools/hooks_static.py` decodes them all, and [hooks.tsv](hooks.tsv) holds the result: 152 requests at
148 distinct main sites.

- All 152 have a name.
- 143 have a main offset. 6 of those are marked `~`.
- 133 have a callback.
- The rest are filled in at run time by the emulator (`tools/emu.py`) or by reading the code.

On the plugin side, every hook is an exlaunch inline hook. The site gets `b stub`, and the stub saves the
registers and calls the callback. A trampoline then runs the displaced instruction and branches back to
site+4. The original code therefore always runs after the callback.

## Against Peanuts' rewrite

`tools/check_changed.py` checks every hook site, and its 16-byte fingerprint window, against Peanuts'
`main.changed.tsv` (34,430 rewritten runs). No hook site and no fingerprint window touches a rewritten
word, so the plugin's own fingerprint checks should pass on Peanuts as they do on console.

## Per-feature verdict

| Module (config) | Hooks (plan site) | Verdict |
| --- | --- | --- |
| Core (core.ini) | AfterContentMount (0x704), shared input, counters, captions | port |
| Shopping Card (shopping-card.ini) | 15 storage, shop and catalog hooks (0x381c) | port |
| Fitting Room (fitting-room.ini) | 11 tailor hooks (0xc270), all at 0x311xxxx | port |
| Catalog (catalog.ini) | 4 badges, 2 cabinet and ground stars, 4 variation labels, 8 dialogue stars, 1 Nook display star | port |
| Pockets (pockets.ini) | 7 stacking, 7 stack split, 2 mailbox, 2 recycling, 4 quick store, 6 storage hint, drag and hold-select | port |
| Faster Dialogue (faster-dialogue.ini) | 5 speed, 2 name, 2 advance and halt (0x391fc, 0x3a770, 0x3e164) | port |
| Controls (controls.ini) | 5 hoover, 8 auto swim, 9 auto traversal, swim camera, 20 short dive, fish, insect and dig, 2 mash boost | port |
| Crafting (crafting.ini) | 12 DIY 3D preview and recipe hooks (0x679cc, 0x68e70), 6 quantity shortcut hooks | port |

Rewriting any of these from scratch is not practical. Each callback is a large C++ routine, not a byte
patch: the 1.1.0 plugin text is 0x94000 bytes. The port keeps the plugin's own code. No hook blocks the
port.

## Design

Peanuts already supports static code mods through xmod:

- `dm/tools/xmod.py` and `patch_nso.py --xmod` lay the modules out in console order (rtld, main, subsdk0-9,
  sdk);
- the loader re-aims each far `b`/`bl` between modules at the real base.

The port uses this support. The plan:

1. **main IPS.** Put `b <stub>` at each of the 148 sites, using the console distance from main to subsdk6
   (computed from real NSO sizes, as xmod.py does).
2. **Patched subsdk6.** Bake one stub and one trampoline per site into the plugin's existing text pools
   (around 0x7a000 and 0x71000). The trampoline's `b site+4` back into main is re-aimed by xmod as well.
   - Displaced PC-relative instructions (adrp, literal loads, branches) need relocatable forms.
   - The stub's callback literal is absolute and sits in text, where xmod `ptr` rows cannot go. Patch
     `exl_inline_hook_impl` (0x7e5b4, float variant 0x7e64c) to read the callback from a per-site data slot
     instead. Leave a null slot uncalled.
3. **Neutralise run-time installs.** On Peanuts, svcMapProcessMemory "succeeds" without mapping, so the
   plugin's alias writes would crash. Patch the installer so it only stores the callback in the site's slot.
   The write PCs are 0x6fd6c, 0x6ff18, 0x6ff28, 0x70470, 0x70b38, 0x790c4, 0x790cc, 0x790d4 and 0x790d8.
   The plugin still reads its config and decides which features to hook. A disabled feature leaves its slot
   null, so its sites pass straight through.

Still open:

- Peanuts has no rtld module, so check how exlaunch's module walk numbers main there (its module mask is at
  plugin 0x2144e8; bit0 is rtld, bit1 is main).
- The emulator places a fake subsdk0 of 0x4000 bytes. Switch it to the real layout before baking.

## Companion (Eden Duo dual-screen package)

The companion is compatible in principle:

- Its manifest carries no code patches, so it cannot collide with the IPS.
- Its native module reads and writes guest memory through the host API and gates on build ID
  FF1D1C05670DB602. Peanuts takes that ID from the main NSO header, which an IPS does not touch.

Still needed: an in-game check of its inventory pages with Pockets stacking on.
