This fork follows upstream [Nitrox](https://github.com/SubnauticaNitrox/Nitrox) plus complete ordered patch queue: [0001](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0001-inherited-launcher-path.patch), [0002](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0002-proton-launcher-path.patch). `patch-queue` owns patches and workflows; generated `main` follows upstream default branch plus that queue. CI validates stable upstream source plus the same queue and nightly source; builds happen at deployment, not in CI.

# Ordered patch queue

1. [0001 — Fix inherited launcher path for embedded servers](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0001-inherited-launcher-path.patch) — retained even when upstream absorbs it; exact reverse-apply proof required.

2. [0002 — Resolve native launcher paths inside Proton](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0002-proton-launcher-path.patch) — normalize Linux paths at game bootstrap; keep Windows paths unchanged.

See [fork maintenance](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/README.md).

---

