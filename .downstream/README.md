# Fork maintenance

Edit full ordered queue and tooling on default `patch-queue`, never generated
`main`. Keep individual numbered patch links in `README-prefix.md` in queue order.

Daily/manual GitHub workflow uses built-in job token. It follows upstream default
(development) branch only, replays queue, publishes source release and advances `main`.
No binaries or deployment happen in CI. Existing upstream/fork tags stay intact.
Identities use `<upstream-version>-YYYY.MM.DD`, Europe/Berlin date, with `.N` for
same-day changes. Unchanged source reuses existing release identity; tags never move.
Release asset `source.json` records version, immutable patched source SHA and SHA-256
of GitHub source archive. `felix pv` resolves latest release and verifies archive
before building locally. Failed synchronization leaves last published release usable.

Exact reverse-apply proof permits absorbed patches, without removing them from
queue. Conflicts stop publication. Upstream selection and fork heads are checked
again before publishing; exact main force-with-lease rejects concurrent updates.
Generated main omits all workflows and control tooling, preserving upstream README
bytes after fork prefix. Builds and game-dependent tests belong to deployment.

Offline check:

```fish
python3 .downstream/test-sync.py
```

Manual synchronization from clean, published `patch-queue` checkout:

```fish
python3 .downstream/sync-upstream.py
```
