# Fork maintenance

Edit patches and tooling on `automation`, not generated `main`. Patches apply in
filename order. Keep README patch links in `README-prefix.md` in that order.

The daily/manual GitHub workflow checks out `automation`, tests replay, then
updates `main` using exact force-with-lease
checks. Upstream source is always official `SubnauticaNitrox/Nitrox` `master`.
GitHub supplies the short-lived `GITHUB_TOKEN`; no personal token is required.
A conflicting push fails rather than overwriting concurrent changes. Patch
conflicts stop publication. `automation` is the GitHub default branch and owns all workflows.

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
