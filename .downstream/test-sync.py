#!/usr/bin/env python3
"""Offline replay check using real Git and the fork's real patch."""
import importlib.util
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
print('Patch replay, upstream adoption, README, workflow isolation and ancestry verified.')
