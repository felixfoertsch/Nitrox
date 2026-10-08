# Fork maintenance

Edit full ordered queue and tooling on default `patch-queue`, never generated
`main`. Keep individual numbered patch links in `README-prefix.md` in queue order.

Daily/manual GitHub workflow uses built-in job token. It validates latest numeric
four-component stable tag and upstream default-branch source with identical queue.
Stable source ships through GitHub Releases' native downloadable source archives;
only nightly source advances `main`. No binaries or deployment happen in CI.
Existing upstream/fork tags stay intact. Stable identities use
`<upstream-tag>-YYYY.MM.DD.N`, Europe/Berlin date and next unused suffix. Unchanged
source reuses existing release identity; tags never move. Nightly source stays
visibly separate on `main`.

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
