# QoL Enhancements for Peanuts Native

Arcusaren's [Quality of Life Enhancements](https://gamebanana.com/mods/727637) 1.1.0 for Animal Crossing: New Horizons 3.0.3, made to work on Peanuts Native. The stock mod doesn't work there, because Peanuts doesn't let plugins patch the game while it runs.

> [!NOTE]
> **How this was made.** Most of this repository - the patcher page, the Python build tools and the docs - was written by Claude (Anthropic) through Claude Code, an AI coding assistant. I direct the work: I decide what gets built, choose between the designs it proposes, and approve each test on my own handheld.
>
> **What Claude did:** took apart the mod's Core plugin to find its 151 hooks, designed the port, wrote the tools, the page and the docs, and tested it in an emulator and on my AYN Thor.
> **What I did:** what to build, the design calls, the go-ahead for every device test, and every release.
> **What I have not done:** a line-by-line review of the code. There is no automated test suite; [docs/PORT.md](docs/PORT.md) lists the checks that were run.
>
> Commits here carry no Claude co-author line, so assume any part of the code may be AI-written. Found a bug? Open an issue.

## Install

1. Download **Main download (Modded Switch)** from the [mod's GameBanana page](https://gamebanana.com/mods/727637).
2. Download `qol-peanuts-patch.json` from the [latest release](https://github.com/catmona/acnh-qol-peanuts/releases/latest).
3. Open the [patcher page](https://catmona.github.io/acnh-qol-peanuts/), pick both files and tap **Make the Peanuts zip**. It works on your phone or a PC, and nothing is uploaded.
4. In Peanuts, open ACNH's settings, then **Install mod… > Zip file** and pick `qol-enhancements-peanuts.zip`. Peanuts rebuilds the game with the mod, which takes about 5 minutes.

Peanuts warns that the mod looks like an exlaunch plugin. You can ignore that.

## Status

Tested on an AYN Thor with Peanuts Native 0.1.7: Core and all seven features load with no errors, and the game runs at its normal 30 fps. The features haven't each been tried in play yet.

## Features

What each module does, and whether it has been tried in play on Peanuts.

- **Pockets** (not checked yet): Grab 5 or Grab 10 from a stack, ZL to drop or release, ZR to use an item, hold A to pick several items in shop and storage menus, Y to send items to storage at home, A to open presents and mail without a menu. Optional stacking for Manila clams and fishing trash.
- **Controls** (not checked yet): hold Y to skip dialogue up to the next choice, or to keep picking up items, crops and weeds. Vaults rivers and climbs cliffs on its own, swims without pressing A, and lets the camera tilt while swimming.
- **Crafting** (not checked yet): faster crafting, the quantity wraps between 1 and 10, Y goes straight to the quantity, and the DIY app shows 3D previews. Cooking too.
- **Faster Dialogue** (not checked yet): text runs faster, with an optional boost for shop and service characters.
- **Catalog** (not checked yet): a star on items, recipes, critters and art you haven't collected yet, including in Nook Shopping and the other catalogs.
- **Shopping Card** (not checked yet): pay at Nook's Cranny, Able Sisters and for storage upgrades from your savings, topped up from your pockets.
- **Fitting Room** (not checked yet): Y adds clothes to a bag so you can buy several at once, X applies a tailor ticket, B skips the "wear them out?" question.
- **Core** (loads; timer not checked yet): needed by the rest. Gives the amiibo scanner 5 minutes instead of 15 seconds.

## How it works

The mod hooks the game by patching its code at run time. Peanuts compiles the game ahead of time, so those patches never land. This port puts the hooks in at build time instead: an IPS patch for the game's `main`, plus a patched copy of the mod's Core plugin. [docs/PORT.md](docs/PORT.md) has the details.

The patch file holds the game's original instruction at each hook site (604 bytes in all), so it ships in Releases and not in the repository. Arcusaren's files are never redistributed: the page patches your own download.

## Building the patch yourself

You need Python 3.12, `pip install -r requirements.txt`, the Switch download extracted into `in/switch/`, and the exefs (`main` and `subsdk0`) of your own copy of ACNH 3.0.3.

```
python tools/build.py --exefs <folder with main and subsdk0>
```

This writes the Peanuts zip, the patch file and the IPS to `out/build/`. The other scripts in `tools/` are the analysis tools behind docs/PORT.md; each one has its usage at the top.

## Credits

Arcusaren for QoL Enhancements, shadowninja108 for exlaunch, and the Peanuts Native authors.

## License

GPL-2.0, the same as the original mod.
