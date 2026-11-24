# QoL Enhancements for Peanuts Native (ACNH 3.0.3)

A port of Arcusaren's [Quality of Life Enhancements](https://gamebanana.com/mods/727637) v1.1.0 for
Animal Crossing: New Horizons 3.0.3 to the Peanuts Native Android host.

Status: work in progress.

## Why a port is needed

Every feature of the mod runs through its Core module (`exefs/subsdk6`), an
[exlaunch](https://github.com/shadowninja108/exlaunch) plugin that hooks the game's `main` at run
time. Peanuts rewrites `main` ahead of time and maps it read-only, and does not implement
`svcSetProcessMemoryPermission`, so run-time hooks never land. This port bakes the hooks in at build
time instead:

- an IPS patch for `main` puts a short jump at each hook site, through a data slot;
- a patched copy of the Core module fills those slots and keeps its trampolines in its own memory,
  instead of asking the kernel to remap `main`.

## What this repository contains

Only tools and patch descriptions. It does not contain the game's code, the mod's binaries, or any
part of Peanuts. You supply the mod zip you downloaded from GameBanana; the tools produce a mod zip
that Peanuts' "Build with mods" accepts.

## License

GPL-2.0, the same as the original mod.
