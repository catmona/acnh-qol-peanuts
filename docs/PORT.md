# Port notes

Tested on Peanuts Native 0.1.7. Build: ACNH 3.0.3, main build ID ff1d1c05670db6021c85b624a710b963.

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
151 distinct main sites (two requests share main+0x192a590). Every row has a name, a callback and a main offset.
The ones the static pass could not resolve were filled in from emulator runs (`tools/emu.py`).

On the plugin side, every hook is an exlaunch inline hook. The site gets `b stub`, and the stub saves the
registers and calls the callback. A trampoline then runs the displaced instruction and branches back to
site+4. The original code therefore always runs after the callback.

## Against Peanuts' rewrite

`tools/check_changed.py` checks every hook site, and its 16-byte fingerprint window, against Peanuts'
`main.changed.tsv` (34,430 rewritten runs). No hook site and no fingerprint window touches a rewritten
word, so the plugin's own fingerprint checks should pass on Peanuts as they do on console.

Peanuts 0.1.8 needs **Graphics > Frame rate cap = Game owned**. Its default 60 fps cap runs a rewritten main
without the xmod relink, so the 151 main-to-subsdk6 branches are never set and the game crashes at start. With
Game owned, QoL runs on 0.1.8 as on 0.1.7: hold-Y skip was checked in game on the Thor.

The cause is on the Peanuts side.

- `scripts/pack_android.py` `rewrite_variants()` rewrites main for the 60 fps variant without `--xmod`, so the pack's
  `60/` folder has no `main.xmod.tsv`. The loader reads the table from that folder when the variant runs.
- The fix is to pass `xmod_files` into `rewrite_variants()` and add `--xmod` (and the xmod key) for each modded module,
  as `rewrite()` already does.
- The variant has the same layout: its rewrite reports the same 151 branches into subsdk6, with none at a rewritten
  instruction.

QoL has no safe fix of its own. Main has no free space big enough for an indirect jump per hook: its unused padding
gaps are 12 bytes at most.

Checked against the 60 fps patch (`tools/check_changed.py` on the variant's `60/main.changed.tsv`, and tmouh's
6,810 changes), no hook site and no signature record is changed:

- Two 16-byte windows share later words with tmouh's changes: UpdatePocketMenu at site+4 and +8, and
  DialogueAdvanceInput at site+12. Neither word is in the plugin's signature table.
- Both words run after the trampoline returns to main. UpdatePocketMenu's trampoline returns into tmouh's
  changed word, its first word, which the xmod table allows. So the two patches can coexist.

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

`tools/build.py --exefs <game exefs>` writes `out/build/`:

- the patched `subsdk6`;
- `ff1d1c05670db6021c85b624a710b963.ips` (IPS32 for main);
- `qol-enhancements-peanuts.zip`, laid out as Atmosphère: `atmosphere/contents/01006F8002326000/{exefs,romfs}` and
  `atmosphere/exefs_patches/qol-peanuts/`. Peanuts' ModImporter reads that layout, and "Build with mods" applies it;
- `qol-peanuts-patch.json`, for the patcher page (`docs/index.html`): the 466 runs of bytes (20,010 in all) the build
  changes in the stock plugin image, the new NSO header, the IPS, and SHA-256s of the stock image and of the output
  `subsdk6`. build.py checks that the patch rebuilds `subsdk6` byte for byte.

The zip and the patch hold 604 bytes copied from the user's own dump of main: the 151 original site words (also the
displaced instructions), packed in plugin text. The plugin's own signature table covers only 37 of the 151 sites, so
they can't come from the mod. The patch goes in Releases only; the zip, which also holds Arcusaren's files, is not
redistributed. This repo stores offsets only (docs/textreads.tsv).

The page applies the patch in the browser: it reads the GameBanana Switch zip, LZ4-decompresses the stock `subsdk6`,
checks its hash, applies the runs, checks the output hash and writes a stored (uncompressed) zip. Run in Node against
the real download, its zip has the same 44 entries with the same hashes as build.py's.

### No Peanuts row needed: the window is in the plugin's bss

An earlier build (07158e2) mapped the window with svcMapPhysicalMemory in the alias region, which needs
`mem_map_limit off` in Peanuts' ACNH game.tsv. The window now lives in subsdk6's own bss instead. Peanuts maps
module bss as anonymous, uncommitted pages, so the zip works on stock Peanuts with no host row.

A copy of all of main's text in bss (63 MB) would not fit. Peanuts' SetHeapSize refuses when the module images
summed, rounded up to 2 MB, leave too little of the app pool (Peanuts Native source, `dm/host/hle_svc.c` 575-590). ACNH's
mem_used (0x7a00000, `dm/games/01006F8002326000/game.tsv`) is the unmodded modules plus 4 MiB
(`dm/games/profile_guess.py` 466-469), so subsdk6 has 4 MiB to live in. So the window is sparse:

| | Size |
| --- | --- |
| Pages copied: each page within 64 bytes of a hook site (119), plus the page after each (96 more, so a read across a page end stays in the copy) | 215 × 4 KiB = 860 KiB |
| Page table: one byte per page of main's text (0 = not copied, else slot + 1) | 16 KiB |
| bss growth | 0xdc000 (880 KiB) |
| subsdk6 image, was 2.09 MiB | 2.94 MiB |

That leaves about 1 MiB of the 4 MiB. On the device Peanuts' rewriter adds a 26 KiB patch area (subsdk6 is 0x308000
there) and SetHeapSize passes (see "Device test"). The window pages are contiguous, so they cost about
55 16 KiB host pages, about 0.9 MB resident on the device (the alias build cost about 3.1 MB).

### How it works

1. **Main IPS.** A `b stub_i` at each of the 151 hook sites. Distances use the console layout (subsdk6 at
   main+0x6072000), and the loader re-aims these far branches.
2. **Module walk.** FindModules starts at main and counts rtld as present. Peanuts has no rtld, but the plugin
   asserts on it in mem_layout.cpp (plugin 0x6e160). The rtld record is a copy of main's record. The walk stops
   after the plugin's own record.
3. **Shadow window** (`shadow_setup`, run at exl init instead of RwPages(main), before any hook goes in). It:
   1. copies each of the 215 pages from the real main into its bss slot;
   2. puts each site's original word back in the copy (the IPS word is already in main by then);
   3. fills the page table for the 119 redirected pages.

   Before this runs the page table is all zero, so a load reads the real main.
4. **Main's record stays real.** The plugin reads main's data through record1 too (for example
   [base+0x4ab2020] at 0x6bd58), so the record cannot point at the window.
5. **Load thunks.** Each plugin load that reads a word the IPS changes is a `b` to its own thunk. There are 307 of
   these, listed in [textreads.tsv](textreads.tsv). The thunk:
   1. saves x16 and x17;
   2. puts the load's address in x17;
   3. calls `xlate`, which looks the address's page up in the page table and, for a copied page, moves it into the
      window; any other address is left alone;
   4. runs the original load from [x17];
   5. restores x16 and x17, skipping a register the load itself wrote;
   6. applies any writeback and branches back.

   The flags and every other register are untouched, so a following compare or branch behaves as before.
6. **No code is written to main at run time.**
   - HookFunc and HookInline (`hook_new`) look up the site and store the callback in SLOTS[i].
   - They also copy the installed word into the window, so the plugin's "publication" re-read sees the change.
   - HookFunc returns the site's trampoline.
   - The inline impls read the callback from SLOTS[i]. An empty slot runs the original code.
7. **Trampolines** run the displaced instruction and branch back to site+4. The 12 displaced PC-relative
   instructions are rebuilt:
   - adrp from record1's start;
   - b, bl, cbz, tbz and b.cond as far forms.

### Patched plugin words

Each one is checked against the stock word before it is patched.

| Plugin offset | Stock | Now |
| --- | --- | --- |
| 0x6e990 | mov x26, #0 | `bl walk_start`: the walk starts at main (far `b main+0` anchor), rtld counted |
| 0x6ea88 | cmp x0, x26 | `b walk_check`: copy record1 into record0 (rtld); stop after the plugin's record |
| 0x6db90 | bl RwPages(main) | `bl shadow_setup` |
| 0x6db94 | bl process-handle setup | nop (svc 0x40/0x8/0x43 are placeholders on Peanuts) |
| 0x70a20 | pool setup | `ret` (no RwPages pools) |
| 0x70a50 | HookFunc entry | `b hook_new` |
| 0x79020 | HookInline entry | `b hook_new` |
| 0x7e5fc, 0x7e6d8 | ldr x20, [x19, #8] | `bl get_cb` (SLOTS[i]) |
| the 307 rows of textreads.tsv | a load from main's text | `b` to that load's thunk (above) |

**Checks.** No check is patched to pass. Every fingerprint and instruction check still runs unchanged, but through
a thunk it now reads the original bytes. The plugin's reporter (plugin 0xf920, the reason codes) is never called
in either verification run below, so there is no reason code to log.

### Verification (tools/emu.py, Peanuts mode)

The emulator models Peanuts' behaviour:

- no rtld;
- 4 KiB free pages past the arena;
- main's text is read-only;
- placeholder svcs;
- far b/bl re-aimed;
- no svcMapPhysicalMemory: the window is the plugin's bss.

`EMU_LAZY=1` is the discovery mode. It keeps main clean and writes each IPS word only when its hook is installed,
which mirrors what the window shows. Its `<out>.<phase>.textreads.txt` gave textreads.tsv, the union of the two
configs below. "Window reads unlike the dump" counts every byte the plugin reads from the bss window that differs
from the dump's main text at that spot (site words aside, which hold the original or the installed word). The
shipped run checked 1,238 window reads.

| Config | Slots filled | Main text writes | IPS words read through real main | Window reads unlike the dump | Reporter calls |
| --- | --- | --- | --- | --- | --- |
| Shipped romfs | 132/151 (19 empty are the Tweaks hooks; tweaks.ini is not shipped) | 0 | 0 | 0 | 0 |
| tweaks.ini on (every option, both show-off times 1500) | 151/151 | 0 | 0 | 0 | 0 |

Every hook ports; none had to be dropped.

### Device test (AYN Thor, Peanuts Native 0.1.7)

The zip was installed with Install mod > Zip file and built with "Build with mods" (5 min 7 s), with no other mods on. The run
used the stock ACNH game.tsv (no `mem_map_limit` row) and `DM_DBG=1` in the game's Extra environment,
which makes Peanuts print the plugin's svcOutputDebugString lines as `[guest]`.

| Check | Log or screen |
| --- | --- |
| subsdk6 loads | `subsdk6: gates 15 patch_off 0x300000`, `base ... size 0x308000` (2.94 MiB image plus the 26 KiB patch area) |
| Branches linked | `xmod: main 151 branches into subsdk6; subsdk6 159 branches into main` |
| Heap budget | `[mem] heap 3.09 GB (heap region 3.25 GB)`: SetHeapSize passed |
| Plugin init | `DT_INIT +0x6dbd0`, then `[QoL Enhancements] Core: 1.1.0; slot=subsdk6; configuration ready` |
| Modules | all 8 report `1.1.0; enabled=true` with their settings: Catalog, Pockets, Faster Dialogue, Fitting Room, Shopping Card, Crafting, Controls (and Core) |
| Dialogue rules | `[QoL Enhancements/Controls] dialogue halt rules=634`, the same count as the emulator run |
| Reason codes | none: no reporter line and no failure line in the whole log |
| Play | the Nook Inc. intro dialogue runs at 30 fps (1% low 27) and advances with A |
| Controls | holding Y in the intro skips the dialogue and stops at each choice and at the name screen |
| Companion | `[peanuts] companion ticks: 1793 in 30.0 s`, 1.88 ms each |

Not checked by hand yet: the companion's inventory pages with Pockets stacking on.

### Residual risks

- Heap budget: settled on the device (above). The rewriter's patch area for subsdk6 is 26 KiB, well inside the
  1 MiB of headroom.
- The companion helper's code block must fit within main + 120 MB (`dm/peanuts/peanuts.c` 435-457), and the
  window adds 0.9 MB to that reach. It fit on the device: `[peanuts] companion ticks: 1793 in 30.0 s`.
- textreads.tsv comes from two traced runs. A check reached only on a path the emulator never ran (for example a
  late-installed hook in a scene it doesn't load) would read through real main, see a branch and turn its own
  feature off. To find one, run `EMU_LAZY=1` and append its textreads output.
- A displaced `bl` returns into plugin text. A callee that checks its return address would notice.

## Companion (Eden Duo dual-screen package)

The companion is compatible in principle:

- Its manifest carries no code patches, so it cannot collide with the IPS.
- Its native module reads and writes guest memory through the host API and gates on build ID
  FF1D1C05670DB602. Peanuts takes that ID from the main NSO header, which an IPS does not touch.

Still needed: an in-game check of its inventory pages with Pockets stacking on.
