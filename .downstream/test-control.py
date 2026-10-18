#!/usr/bin/env python3
"""Real Git control refresh, archive leases and backup checks; no network."""
import ast
import importlib.util
import io
import json
from unittest.mock import patch
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

os.environ.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
TOOLING = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sync', TOOLING / 'sync-upstream.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def commit(repo, message):
	sync.git('add', '-A', cwd=repo)
	sync.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
		'-c', 'commit.gpgsign=false', 'commit', '--quiet', '--allow-empty', '-m', message, cwd=repo)
	return sync.git('rev-parse', 'HEAD', cwd=repo)


def rejects(call):
	try:
		call()
	except (SystemExit, subprocess.CalledProcessError):
		return
	raise AssertionError('Unsafe operation accepted')


with tempfile.TemporaryDirectory() as tmp:
	root = Path(tmp)
	upstream = root / 'upstream'
	sync.git('init', '--quiet', '-b', 'master', str(upstream))
	before = next(ast.literal_eval(n.value) for n in ast.walk(ast.parse((TOOLING / 'test-sync.py').read_text()))
		if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'before' for t in n.targets))
	source = upstream / 'Nitrox.Launcher/Models/Design/ServerEntry.cs'
	source.parent.mkdir(parents=True)
	source.write_text(before)
	patcher = upstream / 'NitroxPatcher/Main.cs'
	patcher.parent.mkdir()
	patcher.write_bytes((TOOLING / 'patcher-fixture.cs').read_bytes())
	(upstream / 'README.md').write_text('# Complete upstream\n\nUntouched bytes\n')
	base = commit(upstream, 'upstream')
	control = root / 'control'
	sync.reconstruct(str(upstream), TOOLING, control, base, control=True)
	old = sync.git('rev-parse', 'HEAD', cwd=control)
	sync.BOOTSTRAP = '0' * 40
	assert sync.control_candidate(str(upstream), control / '.downstream', root / 'noop', base) == old
	# Empty upstream commits require ancestry refresh even with unchanged source bytes.
	advanced = commit(upstream, 'empty upstream advance')
	candidate = root / 'advance'
	new = sync.control_candidate(str(upstream), control / '.downstream', candidate, advanced)
	assert new != old
	assert sync.git('rev-parse', 'HEAD^', cwd=candidate) == advanced
	assert sync.git('rev-parse', old + ':.github/workflows', cwd=control) == sync.git('rev-parse', 'HEAD:.github/workflows', cwd=candidate)
	assert sync.control_candidate(str(upstream), candidate / '.downstream', root / 'noop2', advanced) == new
	assert (candidate / 'README.md').read_bytes() == (TOOLING / 'README-prefix.md').read_bytes() + (upstream / 'README.md').read_bytes()
	second = commit(upstream, 'second advance')
	assert sync.control_candidate(str(upstream), candidate / '.downstream', root / 'second', second) != new
	(control / 'unexpected.cs').write_text('unknown source')
	commit(control, 'unowned customization')
	rejects(lambda: sync.control_candidate(str(upstream), control / '.downstream', root / 'bad', second))
	(upstream / '.downstream').mkdir()
	(upstream / '.downstream/upstream-owned').write_text('collision')
	collision = commit(upstream, 'reserved collision')
	rejects(lambda: sync.reconstruct(str(upstream), TOOLING, root / 'collision', collision, control=True))
	bundle = root / 'control.bundle'
	digest = sync.verified_bundle(candidate, new, bundle)
	assert len(digest) == 64
	rejects(lambda: sync.verified_bundle(candidate, '0' * 40, root / 'invalid.bundle'))
	remote = root / 'remote.git'
	sync.git('init', '--quiet', '--bare', str(remote))
	sync.git('push', '--quiet', str(remote), old + ':refs/heads/patch-queue', cwd=candidate)
	sync.archive_push(candidate, str(remote), old, new)
	assert sync.git('rev-parse', 'refs/tags/archive/patch-queue/' + old, cwd=remote) == old
	rejects(lambda: sync.archive_push(candidate, str(remote), old, new))
	# Existing wrong archive is never retagged.
	sync.git('update-ref', 'refs/tags/archive/patch-queue/' + new, old, cwd=remote)
	rejects(lambda: sync.archive_push(candidate, str(remote), new, new))
	# Annotated archive resolving to old is still forbidden: tag must directly name commit.
	sync.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', '-c', 'tag.gpgsign=false',
		'tag', '-a', 'annotated', '-m', 'archive', new, cwd=candidate)
	annotated = sync.git('rev-parse', 'refs/tags/annotated', cwd=candidate)
	sync.git('push', '--quiet', str(remote), 'refs/tags/annotated:refs/tags/annotation-object', cwd=candidate)
	sync.git('update-ref', 'refs/tags/archive/patch-queue/' + new, annotated, cwd=remote)
	rejects(lambda: sync.archive_push(candidate, str(remote), new, new))
	# Post-push remote readback failure blocks caller before dispatch.
	for readback in ('missing', 'wrong', 'error'):
		probe = root / ('readback-' + readback + '.git')
		sync.git('init', '--quiet', '--bare', str(probe))
		sync.git('push', '--quiet', str(probe), old + ':refs/heads/patch-queue', cwd=candidate)
		real_git = sync.git
		def readback_git(*args, **kwargs):
			if args[0] == 'ls-remote' and len(args) == 4:
				if readback == 'error':
					raise subprocess.CalledProcessError(1, ['git', 'ls-remote'])
				return '' if readback == 'missing' else old + '\trefs/heads/patch-queue'
			return real_git(*args, **kwargs)
		with patch.object(sync, 'git', side_effect=readback_git):
			rejects(lambda: sync.archive_push(candidate, str(probe), old, new))
	# Servers lacking atomic support must leave both refs untouched.
	for supported in ('false', 'true'):
		blocked = root / ('blocked-' + supported + '.git')
		sync.git('init', '--quiet', '--bare', str(blocked))
		sync.git('push', '--quiet', str(blocked), old + ':refs/heads/patch-queue', cwd=candidate)
		sync.git('config', 'receive.advertiseAtomic', supported, cwd=blocked)
		if supported == 'true':
			hook = blocked / 'hooks/pre-receive'
			hook.write_text('#!/bin/sh\nexit 1\n')
			hook.chmod(0o755)
		rejects(lambda: sync.archive_push(candidate, str(blocked), old, new))
		assert sync.git('rev-parse', 'refs/heads/patch-queue', cwd=blocked) == old
		assert not sync.git('ls-remote', str(blocked), 'refs/tags/archive/*')
	# Concurrent control moves after preflight: exact server lease rejects branch and archive atomically.
	raced = root / 'raced.git'
	sync.git('init', '--quiet', '--bare', str(raced))
	sync.git('push', '--quiet', str(raced), old + ':refs/heads/patch-queue', cwd=candidate)
	real_git = sync.git
	def race_git(*args, **kwargs):
		if args[:2] == ('push', '--atomic'):
			real_git('update-ref', 'refs/heads/patch-queue', advanced, cwd=raced)
		return real_git(*args, **kwargs)
	# Populate new object without altering control until inside push boundary.
	sync.git('push', '--quiet', str(raced), new + ':refs/heads/objects', cwd=candidate)
	with patch.object(sync, 'git', side_effect=race_git):
		rejects(lambda: sync.archive_push(candidate, str(raced), old, new))
	assert sync.git('rev-parse', 'refs/heads/patch-queue', cwd=raced) == advanced
	assert not sync.git('ls-remote', str(raced), 'refs/tags/archive/*')
	# Real upstream race makes freshness fail before any promotion.
	selected = sync.selection(str(upstream))
	commit(upstream, 'raced upstream')
	rejects(lambda: sync.check_fresh(str(upstream), selected, str(remote), new, ''))
	# Dispatch failure happens after verified promotion; next candidate is no-op.
	with patch.object(sync.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['gh'])):
		rejects(lambda: sync.dispatch_control(new))
	sync.git('update-ref', 'refs/heads/master', advanced, cwd=upstream)
	assert sync.control_candidate(str(upstream), candidate / '.downstream', root / 'recovery', advanced) == new
	assert not sync.source_identity('1.9.0.0', {'refs/tags/archive/patch-queue/' + old: old}, new, '2026.10.18').startswith('archive/')

# Strict dispatch API contract: branch ref plus independent exact-SHA binding.
for intent in ('false', 'true'):
	os.environ['REBUILD'] = intent
	def dispatch_api(command, **kwargs):
		payload = json.loads(kwargs['input'])
		assert payload['ref'] == 'patch-queue'
		assert payload['inputs'] == {'expected_control': 'a' * 40, 'rebuild': intent}
		return subprocess.CompletedProcess(command, 204)
	with patch.object(sync.subprocess, 'run', side_effect=dispatch_api):
		sync.dispatch_control('a' * 40)
os.environ.pop('REBUILD')

# Failed dispatch needs no special marker: next scheduled no-op enters publication again.
with tempfile.TemporaryDirectory() as tmp:
	old = 'a' * 40
	def current_git(*args, **kwargs):
		if args == ('status', '--porcelain'):
			return ''
		if args == ('rev-parse', 'HEAD'):
			return old
		if args[:2] == ('remote', 'get-url'):
			return 'https://example.invalid/fork.git'
		if args[0] == 'ls-remote':
			return old + '\trefs/heads/patch-queue\n' + 'b' * 40 + '\trefs/heads/main'
		return ''
	with patch.object(sync, 'git', side_effect=current_git), patch.object(sync, 'selection', return_value=('refs/heads/master', 'c' * 40)), \
		patch.object(sync, 'control_candidate', return_value=old), patch.object(sync, 'reconstruct') as replay, \
		patch.object(sync, 'check_fresh'), patch.object(sync, 'configure_auth'), patch.object(sync, 'publish_source') as publish:
		sync.refresh('prepare', Path(tmp))
		assert json.loads((Path(tmp) / 'refresh.json').read_text())['new'] == old
		sync.main()
		assert replay.call_count == 1 and publish.call_count == 1

# Existing release: repair missing manifest, reject mismatched bytes, never overwrite.
with tempfile.TemporaryDirectory() as tmp:
	work = Path(tmp) / 'source'
	work.mkdir()
	(work / 'Directory.Build.props').write_text('<Project><Version>1.9.0.0</Version></Project>')
	tag, source = '1.9.0.0-2026.10.10.1', 'a' * 40
	expected = {'version': tag, 'source': source, 'sha256': sync.hashlib.sha256(b'archive').hexdigest()}
	for manifest in (None, expected, dict(expected, sha256='wrong')):
		writes = []
		def api(command, **kwargs):
			if '--paginate' in command:
				return tag + '\n'
			if 'Accept: application/octet-stream' in command:
				return json.dumps(manifest).encode()
			return json.dumps({'draft': False, 'assets': [] if manifest is None else [{'name': 'source.json', 'id': 1}]}).encode()
		with patch.object(sync, 'git', side_effect=lambda *args, **kwargs: source + '\trefs/tags/' + tag if args[0] == 'ls-remote' else source), \
			patch.object(sync, 'check_fresh'), patch.object(sync.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'archive')), \
			patch.object(sync.subprocess, 'check_output', side_effect=api), \
			patch.object(sync.subprocess, 'run', side_effect=lambda command, **kwargs: writes.append(command)):
			if manifest is not None and manifest != expected:
				rejects(lambda: sync.publish_source(work, ('refs/heads/master', source), 'remote', source, source))
				assert not writes
			else:
				sync.publish_source(work, ('refs/heads/master', source), 'remote', source, source)
				assert len(writes) == (1 if manifest is None else 0), writes
				if writes:
					assert writes[0][:3] == ['gh', 'release', 'upload'] and '--clobber' not in writes[0]
					assert json.loads((work.parent / 'source.json').read_text()) == expected

# Credential and dispatch boundaries fail before candidate construction or publication.
with tempfile.TemporaryDirectory() as tmp:
	original_git, original_selection = sync.git, sync.selection
	try:
		sync.git = lambda *args, **kwargs: ('a' * 40 if args == ('rev-parse', 'HEAD') else
			'https://example.invalid/fork.git' if args[:2] == ('remote', 'get-url') else
			'a' * 40 + '\trefs/heads/patch-queue')
		sync.selection = lambda upstream: ('refs/heads/master', 'b' * 40)
		os.environ['EXPECTED_CONTROL'] = 'c' * 40
		rejects(lambda: sync.refresh('prepare', Path(tmp)))
		os.environ.pop('EXPECTED_CONTROL')
		os.environ['GH_TOKEN'] = 'test-only-not-a-credential'
		rejects(lambda: sync.refresh('prepare', Path(tmp)))
	finally:
		sync.git, sync.selection = original_git, original_selection
		os.environ.pop('EXPECTED_CONTROL', None)
		os.environ.pop('GH_TOKEN', None)

workflow = (TOOLING.parent / '.github/workflows/downstream.yml').read_text()
for guard in ('contents: write', 'actions: write', 'persist-credentials: false', 'retention-days: 90',
	'actions/download-artifact@v4', "needs.check.outputs.changed != 'true'"):
	assert guard in workflow
print('Control no-op, two upstream advances, ancestry, README, workflow tree, unqueued/collision rejection, bundle restore, atomic archive and stale lease verified.')
