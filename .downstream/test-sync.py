#!/usr/bin/env python3
"""Offline replay check using real Git and the fork's real patch."""
import importlib.util
import os
os.environ.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
from pathlib import Path
import tempfile

TOOLING = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sync', TOOLING / 'sync-upstream.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

with tempfile.TemporaryDirectory() as tmp:
	root = Path(tmp)
	upstream = root / 'official'
	sync.git('init', '--quiet', '-b', 'master', str(upstream))
	source = upstream / 'Nitrox.Launcher/Models/Design/ServerEntry.cs'
	source.parent.mkdir(parents=True)
	before = '''                // Assist server with finding launcher location.
                if (Directory.Exists(launcherPath))
                {
                    startInfo.EnvironmentVariables.Add(NitroxUser.LAUNCHER_PATH_ENV_KEY, launcherPath);
                }
                if (isEmbeddedMode)
                {
'''
	source.write_text(before)
	patcher = upstream / 'NitroxPatcher/Main.cs'
	patcher.parent.mkdir(parents=True)
	patcher.write_bytes((TOOLING / 'patcher-fixture.cs').read_bytes())
	(upstream / 'README.md').write_text('# Official Nitrox\n')
	workflow = upstream / '.github/workflows/upstream.yml'
	workflow.parent.mkdir(parents=True)
	workflow.write_text('name: upstream\n')
	sync.git('add', '.', cwd=upstream)
	sync.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
		'commit', '--quiet', '-m', 'fixture', cwd=upstream)
	base = sync.git('rev-parse', 'HEAD', cwd=upstream)
	work = root / 'patched'
	assert sync.reconstruct(str(upstream), TOOLING, work) == base
	assert sync.git('rev-parse', 'HEAD^', cwd=work) == base
	assert (work / source.relative_to(upstream)).read_text() == before.replace(
		'EnvironmentVariables.Add(NitroxUser.LAUNCHER_PATH_ENV_KEY, launcherPath);',
		'EnvironmentVariables[NitroxUser.LAUNCHER_PATH_ENV_KEY] = launcherPath;')
	assert (work / 'README.md').read_text().startswith('This fork follows upstream [Nitrox]')
	assert not (work / '.downstream').exists()
	repeat = root / 'repeat'
	sync.reconstruct(str(upstream), TOOLING, repeat)
	assert sync.git('rev-parse', 'HEAD', cwd=repeat) == sync.git('rev-parse', 'HEAD', cwd=work)
	sync.git('tag', '1.8.0.0', cwd=upstream)
	sync.git('tag', '1.8.1.0', cwd=upstream)
	sync.git('tag', '99.0.0.0-beta', cwd=upstream)
	selected = sync.selection(str(upstream))
	assert selected == ('refs/heads/master', base, '1.8.1.0', base)
	sync.git('branch', 'patch-queue', cwd=upstream)
	sync.git('branch', 'main', cwd=upstream)
	sync.check_fresh(str(upstream), selected, str(upstream), base, base)
	assert (work / 'README.md').read_text().split('\n---\n\n', 1)[1] == '# Official Nitrox\n'
	assert (work / 'README.md').read_text() == (TOOLING / 'README-prefix.md').read_text() + '# Official Nitrox\n'
	assert not (work / '.github/workflows/upstream.yml').exists()
	assert not (work / '.github/workflows').exists()
	# Exact upstream adoption is accepted; arbitrary conflicts still fail.
	source.write_text((work / source.relative_to(upstream)).read_text())
	sync.git('add', '.', cwd=upstream)
	sync.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
		'commit', '--quiet', '-m', 'absorb patch', cwd=upstream)
	adopted = root / 'adopted'
	sync.reconstruct(str(upstream), TOOLING, adopted)
	assert (adopted / source.relative_to(upstream)).read_text() == source.read_text()
	try:
		sync.check_fresh(str(upstream), selected, str(upstream), base, base)
		raise AssertionError('Stale upstream accepted')
	except SystemExit:
		pass
	fresh = sync.selection(str(upstream))
	for queue, main in [('0' * 40, base), (base, '0' * 40)]:
		try:
			sync.check_fresh(str(upstream), fresh, str(upstream), queue, main)
			raise AssertionError('Concurrent fork change accepted')
		except SystemExit:
			pass
	source.write_text(before.replace('EnvironmentVariables.Add', 'EnvironmentVariables.Remove'))
	sync.git('add', '.', cwd=upstream)
	sync.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
		'commit', '--quiet', '-m', 'conflict', cwd=upstream)
	try:
		sync.reconstruct(str(upstream), TOOLING, root / 'conflict')
		raise AssertionError('Conflict accepted')
	except sync.subprocess.CalledProcessError:
		pass
assert sync.stable_identity('1.8.1.0', {}, 'a', '2026.10.08') == '1.8.1.0-2026.10.08.1'
refs = {'refs/tags/1.8.1.0-2026.10.08.1': 'a', 'refs/tags/1.8.1.0-2026.10.08.3': 'b'}
assert sync.stable_identity('1.8.1.0', refs, 'a', '2026.10.08') == '1.8.1.0-2026.10.08.1'
assert sync.stable_identity('1.8.1.0', refs, 'c', '2026.10.08') == '1.8.1.0-2026.10.08.4'
workflow = (TOOLING.parent / '.github/workflows/downstream.yml').read_text()
assert 'uses: actions/checkout@v6' in workflow
assert 'ref: ${{ github.sha }}' in workflow
assert 'persist-credentials: false' in workflow
assert "github.ref == 'refs/heads/patch-queue'" in workflow
print('Deterministic replay, selection, freshness, races, absorption, conflicts, README, workflow guards and source identities verified.')
