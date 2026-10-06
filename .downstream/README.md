# Fork maintenance

Edit patches and tooling on `automation`, not generated `main`. Patches apply in
filename order. Keep README patch links in `README-prefix.md` in that order.

The daily/manual GitHub workflow checks out `automation`, tests replay, then
atomically updates `main` and pristine `upstream` using exact force-with-lease
checks. Upstream source is always official `SubnauticaNitrox/Nitrox` `master`.
Set repository secret `CUSTOM_RELEASE_PUSH_TOKEN` to a token with contents and
workflow-write permission before running scheduled synchronization.
A conflicting push fails rather than overwriting concurrent changes. Patch
conflicts stop publication. `main` remains the GitHub default branch.

Offline check:

```fish
python3 .downstream/test-sync.py
```

Manual synchronization from a clean, published `automation` checkout:

```fish
python3 .downstream/sync-upstream.py
```

The launcher patch replaces an inherited launcher-path environment value rather
than attempting to add a duplicate key. No build or release publishing is added;
upstream releases remain unchanged. Game-dependent builds/tests require the
upstream development setup.
