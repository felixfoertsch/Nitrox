This fork follows upstream [Nitrox](https://github.com/SubnauticaNitrox/Nitrox) plus complete ordered patch queue: [0001](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0001-inherited-launcher-path.patch), [0002](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0002-proton-launcher-path.patch), [0003](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0003-server-data-path.patch). `patch-queue` owns patches and workflows; generated `main` follows upstream default branch plus that queue. Daily CI publishes dated development source releases with `source.json` containing immutable source SHA and archive checksum; builds happen at deployment, not in CI. Stable releases are not followed.

# Ordered patch queue

1. [0001 — Fix inherited launcher path for embedded servers](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0001-inherited-launcher-path.patch) — retained even when upstream absorbs it; exact reverse-apply proof required.

2. [0002 — Resolve native launcher paths inside Proton](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0002-proton-launcher-path.patch) — normalize Linux paths at game bootstrap; keep Windows paths unchanged.

3. [0003 — Forward canonical data path to embedded servers](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/patches/0003-server-data-path.patch) — derive data root from selected save, preserving launcher/server agreement.

See [fork maintenance](https://github.com/felixfoertsch/Nitrox/blob/patch-queue/.downstream/README.md).

---

