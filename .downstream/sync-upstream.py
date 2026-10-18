#!/usr/bin/env python3
"""Replay patches on upstream development; publish immutable dated source releases."""
import base64
import hashlib
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo
import os
from pathlib import Path
import re
import subprocess
import tempfile
import shutil
import sys

REPO = 'felixfoertsch/Nitrox'
CONTROL_FILES = (
	'.downstream/README.md', '.downstream/README-prefix.md',
	'.downstream/sync-upstream.py', '.downstream/test-sync.py',
	'.downstream/test-control.py', '.downstream/patcher-fixture.cs',
	'.downstream/patches/0001-inherited-launcher-path.patch',
	'.downstream/patches/0002-proton-launcher-path.patch',
	'.downstream/patches/0003-server-data-path.patch',
	'.github/workflows/downstream.yml',
)
BOOTSTRAP = '32f9cff6d0374a2974e4d98fefb9ea08e4d2c86b'
# Do not load user hooks, filters, signing, or credential helpers during reconstruction.
os.environ.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)

UPSTREAM = 'https://github.com/SubnauticaNitrox/Nitrox.git'


def git(*args, cwd=None):
	return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def selection(upstream):
	lines = git('ls-remote', '--symref', upstream, 'HEAD').splitlines()
	branch = next(line.split()[1] for line in lines if line.startswith('ref:'))
	nightly = next(line.split()[0] for line in lines if line.endswith('\tHEAD') and not line.startswith('ref:'))
	return branch, nightly


def reconstruct(upstream, tooling, destination, revision=None, control=False, default_ref=None):
	git('clone', '--quiet', '--no-checkout', upstream, str(destination))
	git('checkout', '--quiet', '--detach', revision or 'origin/HEAD', cwd=destination)
	base = git('rev-parse', 'HEAD', cwd=destination)
	if git('ls-tree', base, '--', '.downstream', '.github/workflows/downstream.yml', cwd=destination):
		raise SystemExit('Upstream owns reserved control paths')
	patches = sorted((tooling / 'patches').glob('*.patch'))
	if not patches or any(not re.match(r'\d{4}-.+\.patch$', patch.name) for patch in patches):
		raise SystemExit('Invalid ordered patch queue')
	for patch in patches:
		path = str(patch.resolve())
		check = subprocess.run(['git', 'apply', '--check', path], cwd=destination,
			stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		if check.returncode == 0:
			git('apply', path, cwd=destination)
		else:
			# Exact reverse proof accepts absorption, never arbitrary conflicts.
			git('apply', '--reverse', '--check', path, cwd=destination)
			print('Already included upstream: ' + patch.name)
	readme = destination / 'README.md'
	readme.write_bytes((tooling / 'README-prefix.md').read_bytes() + readme.read_bytes())
	git('rm', '-r', '--ignore-unmatch', '.github/workflows', cwd=destination)
	if control:
		for name in CONTROL_FILES:
			target = destination / name
			target.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(tooling.parent / name, target)
		(destination / '.downstream/upstream.json').write_text(json.dumps(
			{'repository': UPSTREAM, 'ref': default_ref or selection(upstream)[0], 'base': base}, sort_keys=True) + '\n')
	git('add', '-A', cwd=destination)
	date = git('show', '-s', '--format=%cI', base, cwd=destination)
	env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
	subprocess.run(['git', '-c', 'user.name=Nitrox Fork', '-c', 'user.email=actions@felixfoertsch.de',
		'-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'apply Nitrox fork patches [skip ci]'],
		cwd=destination, env=env, check=True)
	git('merge-base', '--is-ancestor', base, 'HEAD', cwd=destination)
	return base


def control_candidate(upstream, tooling, destination, revision):
	"""Only trusted old control calls this; candidate code is never imported."""
	old = git('rev-parse', 'HEAD', cwd=tooling.parent)
	owned = set(CONTROL_FILES)
	actual = set(git('ls-files', '.downstream', '.github/workflows', cwd=tooling.parent).splitlines())
	metadata = tooling / 'upstream.json'
	if metadata.exists():
		owned.add('.downstream/upstream.json')
	if actual != owned:
		raise SystemExit('Unknown control path or missing owned file')
	# Bootstrap has known historical direct source/README drift. No other drift is accepted.
	if subprocess.run(['git', 'merge-base', '--is-ancestor', BOOTSTRAP, old], cwd=tooling.parent,
		stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
		baseline = BOOTSTRAP
	else:
		baseline = old
	with tempfile.TemporaryDirectory() as tmp:
		proof = Path(tmp) / 'proof'
		if baseline == BOOTSTRAP:
			changed = git('diff', '--name-only', baseline, old, cwd=tooling.parent).splitlines()
			if any(name not in owned for name in changed):
				raise SystemExit('Unknown unqueued source customization')
		else:
			previous = json.loads(metadata.read_text())
			selected = selection(upstream)
			if previous['repository'] != UPSTREAM or previous['ref'] != selected[0]:
				raise SystemExit('Upstream repository/default ref changed')
			git('fetch', '--quiet', upstream, revision, cwd=tooling.parent)
			git('merge-base', '--is-ancestor', previous['base'], revision, cwd=tooling.parent)
			parent = previous['base']
			reconstruct(str(tooling.parent), tooling, proof, parent, control=True, default_ref=previous['ref'])
			if git('rev-parse', 'HEAD^{tree}', cwd=proof) != git('rev-parse', old + '^{tree}', cwd=tooling.parent):
				raise SystemExit('Unknown unqueued source customization')
	reconstruct(upstream, tooling, destination, revision, control=True)
	git('fetch', '--quiet', str(tooling.parent), old, cwd=destination)
	if git('rev-parse', 'HEAD:.github/workflows', cwd=destination) != git('rev-parse', old + ':.github/workflows', cwd=tooling.parent):
		raise SystemExit('Workflow tree changed during refresh')
	if git('rev-parse', 'HEAD^{tree}', cwd=destination) == git('rev-parse', old + '^{tree}', cwd=tooling.parent):
		if subprocess.run(['git', 'merge-base', '--is-ancestor', revision, old], cwd=destination).returncode == 0:
			return old
	return git('rev-parse', 'HEAD', cwd=destination)


def verified_bundle(repository, old, output):
	"""Self-contained bundle, checked by restoring into an empty repository."""
	git('bundle', 'create', str(output), '--all', cwd=repository)
	with tempfile.TemporaryDirectory() as tmp:
		git('init', '--quiet', '--bare', tmp)
		git('bundle', 'verify', str(output), cwd=tmp)
		git('fetch', '--quiet', str(output), '+refs/*:refs/*', cwd=tmp)
		git('cat-file', '-e', old + '^{commit}', cwd=tmp)
		git('fsck', '--full', '--no-reflogs', cwd=tmp)
		if git('rev-parse', old, cwd=tmp) != old:
			raise SystemExit('Backup restored wrong control')
	return hashlib.sha256(output.read_bytes()).hexdigest()


def archive_push(work, remote, old, new):
	if git('ls-remote', remote, 'refs/heads/patch-queue').split()[0] != old:
		raise SystemExit('Stale control before atomic push')
	archive = 'refs/tags/archive/patch-queue/' + old
	found = git('ls-remote', remote, archive)
	if found and found.split()[0] != old:
		raise SystemExit('Archive tag does not point directly to old control')
	args = ['push', '--atomic', '--force-with-lease=refs/heads/patch-queue:' + old]
	args += ['--force-with-lease=' + archive + ':' + (old if found else '')]
	args += [remote, new + ':refs/heads/patch-queue']
	if not found:
		args += [old + ':' + archive]
	git(*args, cwd=work)
	actual = dict((ref, sha) for sha, ref in (line.split() for line in
		git('ls-remote', remote, 'refs/heads/patch-queue', archive).splitlines()))
	if actual != {'refs/heads/patch-queue': new, archive: old}:
		raise SystemExit('Atomic refresh readback mismatch; refusing dispatch')


def dispatch_control(new):
	intent = os.environ.get('REBUILD', 'false')
	if intent not in ('true', 'false'):
		raise SystemExit('Invalid rebuild intent')
	payload = json.dumps({'ref': 'patch-queue', 'inputs': {'expected_control': new, 'rebuild': intent}})
	subprocess.run(['gh', 'api', '--method', 'POST', 'repos/' + REPO + '/actions/workflows/downstream.yml/dispatches',
		'--input', '-'], input=payload, text=True, check=True)


def refresh(mode, directory):
	tooling = Path(__file__).resolve().parent
	old = git('rev-parse', 'HEAD')
	remote = git('remote', 'get-url', 'origin')
	selected = selection(UPSTREAM)
	refs = dict((ref, sha) for sha, ref in (line.split() for line in git('ls-remote', '--heads', remote).splitlines()))
	if refs.get('refs/heads/patch-queue') != old:
		raise SystemExit('Stale control run')
	if os.environ.get('EXPECTED_CONTROL') and os.environ['EXPECTED_CONTROL'] != old:
		raise SystemExit('Dispatch bound to different control')
	if mode == 'prepare':
		if os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN'):
			raise SystemExit('Candidate checks must not receive write credentials')
		new = control_candidate(UPSTREAM, tooling, directory / 'candidate', selected[1])
		data = dict(old=old, new=new, selected=selected, main=refs.get('refs/heads/main', ''))
		if old != new:
			data['sha256'] = verified_bundle(tooling.parent, old, directory / 'control.bundle')
		(directory / 'refresh.json').write_text(json.dumps(data, sort_keys=True))
		with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a') as output:
			output.write('changed=' + str(old != new).lower() + '\n')
		return
	data = json.loads((directory / 'refresh.json').read_text())
	if data['old'] != old or data['selected'] != list(selected):
		raise SystemExit('Stale refresh manifest')
	if data['new'] == old:
		return
	bundle = directory / 'control.bundle'
	if hashlib.sha256(bundle.read_bytes()).hexdigest() != data['sha256']:
		raise SystemExit('Uploaded backup hash mismatch')
	# Verify downloaded backup, not merely its declared hash.
	with tempfile.TemporaryDirectory() as tmp:
		git('init', '--quiet', '--bare', tmp)
		git('bundle', 'verify', str(bundle.resolve()), cwd=tmp)
		git('fetch', '--quiet', str(bundle.resolve()), '+refs/*:refs/*', cwd=tmp)
		git('cat-file', '-e', old + '^{commit}', cwd=tmp)
		git('fsck', '--full', '--no-reflogs', cwd=tmp)
	token = os.environ.pop('GH_TOKEN', None)
	with tempfile.TemporaryDirectory() as tmp:
		work = Path(tmp) / 'candidate'
		new = control_candidate(UPSTREAM, tooling, work, selected[1])
		if new != data['new']:
			raise SystemExit('Independent reconstruction differs')
		check_fresh(UPSTREAM, selected, remote, old, data['main'])
		if token:
			os.environ['GH_TOKEN'] = token
		configure_auth()
		archive_push(work, remote, old, new)
		# Token pushes do not trigger push workflows. Failure remains fatal; next schedule recovers.
		dispatch_control(new)


def configure_auth():
	if os.environ.get('GITHUB_ACTIONS') == 'true':
		token = os.environ.get('GH_TOKEN')
		if not token:
			raise SystemExit('GH_TOKEN is required in GitHub Actions')
		auth = base64.b64encode(('x-access-token:' + token).encode()).decode()
		print('::add-mask::' + auth, flush=True)
		os.environ.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
			GIT_CONFIG_VALUE_0='AUTHORIZATION: basic ' + auth)


def check_fresh(upstream, selected, remote, queue, main):
	if selection(upstream) != selected:
		raise SystemExit('Upstream changed during patch replay')
	refs = dict((ref, sha) for sha, ref in
		(line.split() for line in git('ls-remote', '--heads', remote).splitlines()))
	if refs.get('refs/heads/patch-queue') != queue or refs.get('refs/heads/main', '') != main:
		raise SystemExit('Fork changed during patch replay')


def source_identity(version, refs, source, day):
	prefix = version + '-' + day
	matches = [(0 if ref == 'refs/tags/' + prefix else int(ref[len('refs/tags/' + prefix + '.'):]), sha)
		for ref, sha in refs.items()
		if ref == 'refs/tags/' + prefix or re.fullmatch(re.escape('refs/tags/' + prefix) + r'\.\d+', ref)]
	for number, sha in sorted(matches):
		if sha == source:
			return prefix + ('.' + str(number) if number else '')
	number = max((number for number, _ in matches), default=-1) + 1
	return prefix + ('.' + str(number) if number else '')


def publish_source(work, selected, remote, queue, main):
	refs = dict((ref, sha) for sha, ref in
		(line.split() for line in git('ls-remote', '--tags', remote).splitlines()))
	source = git('rev-parse', 'HEAD', cwd=work)
	version = ET.parse(work / 'Directory.Build.props').findtext('.//{*}Version')
	if not version or not re.fullmatch(r'\d+(?:\.\d+){3}', version):
		raise SystemExit('Invalid upstream version')
	# Reuse existing source identity across days; retry missing release, never retag.
	tag = next((ref.removeprefix('refs/tags/') for ref, sha in refs.items()
		if sha == source and re.fullmatch(re.escape('refs/tags/' + version) +
			r'-\d{4}\.\d{2}\.\d{2}(?:\.\d+)?', ref)), None)
	if tag is None:
		tag = source_identity(version, refs, source,
			datetime.now(ZoneInfo('Europe/Berlin')).strftime('%Y.%m.%d'))
		check_fresh(UPSTREAM, selected, remote, queue, main)
		git('-c', 'tag.gpgsign=false', 'tag', tag, cwd=work)
		git('push', '--force-with-lease=refs/tags/' + tag + ':',
			remote, 'refs/tags/' + tag, cwd=work)
	releases = subprocess.check_output(['gh', 'api', '--paginate',
		'repos/felixfoertsch/Nitrox/releases', '--jq', '.[].tag_name'], text=True).splitlines()
	if tag not in releases:
		check_fresh(UPSTREAM, selected, remote, queue, main)
		url = 'https://api.github.com/repos/felixfoertsch/Nitrox/tarball/' + source
		with urllib.request.urlopen(url, timeout=60) as response:
			checksum = hashlib.sha256(response.read()).hexdigest()
		manifest = work.parent / 'source.json'
		manifest.write_text(json.dumps({'version': tag, 'source': source, 'sha256': checksum}))
		subprocess.run(['gh', 'release', 'create', tag, str(manifest), '--repo', 'felixfoertsch/Nitrox',
			'--verify-tag', '--latest', '--title', 'Development source ' + tag,
			'--notes', 'Source-only release. Builds happen at deployment.\n\nUpstream: ' +
			selected[1] + '\nPatched source: ' + source + '\nPatch queue: ' + queue], check=True)
	# Never skip an existing release without checking actual immutable archive and manifest bytes.
	url = 'https://api.github.com/repos/' + REPO + '/tarball/' + source
	with urllib.request.urlopen(url, timeout=60) as response:
		checksum = hashlib.file_digest(response, 'sha256').hexdigest()
	expected = {'version': tag, 'source': source, 'sha256': checksum}
	release = json.loads(subprocess.check_output(['gh', 'api', 'repos/' + REPO + '/releases/tags/' + tag], text=True))
	assets = [asset for asset in release['assets'] if asset['name'] == 'source.json']
	if len(assets) > 1:
		raise SystemExit('Duplicate source manifest')
	if assets:
		manifest_bytes = subprocess.check_output(['gh', 'api', '-H', 'Accept: application/octet-stream',
			'repos/' + REPO + '/releases/assets/' + str(assets[0]['id'])])
		if json.loads(manifest_bytes) != expected:
			raise SystemExit('Published source manifest mismatch; refusing overwrite')
	else:
		check_fresh(UPSTREAM, selected, remote, queue, main)
		manifest = work.parent / 'source.json'
		manifest.write_text(json.dumps(expected))
		subprocess.run(['gh', 'release', 'upload', tag, str(manifest), '--repo', REPO], check=True)
	if release['draft']:
		check_fresh(UPSTREAM, selected, remote, queue, main)
		subprocess.run(['gh', 'release', 'edit', tag, '--draft=false', '--repo', REPO], check=True)
	print('Development source: ' + source + ' https://github.com/felixfoertsch/Nitrox/releases/tag/' + tag)


def upstream_unchanged(event, parent, selected):
	return event == 'schedule' and parent == selected[1]


def main():
	if git('status', '--porcelain'):
		raise SystemExit('Working tree must be clean')
	tooling = Path(__file__).resolve().parent
	remote = git('remote', 'get-url', 'origin')
	refs = dict((ref, sha) for sha, ref in
		(line.split() for line in git('ls-remote', '--heads', remote).splitlines()))
	queue = git('rev-parse', 'HEAD')
	if refs.get('refs/heads/patch-queue') != queue:
		raise SystemExit('HEAD must match published patch-queue')
	selected = selection(UPSTREAM)
	if os.environ.get('EXPECTED_CONTROL') and os.environ['EXPECTED_CONTROL'] != queue:
		raise SystemExit('Dispatch bound to different control')
	token = os.environ.pop('GH_TOKEN', None)
	with tempfile.TemporaryDirectory() as tmp:
		root = Path(tmp)
		work = root / 'nightly'
		reconstruct(UPSTREAM, tooling, work, selected[1])
		check_fresh(UPSTREAM, selected, remote, queue, refs.get('refs/heads/main', ''))
		git('remote', 'set-url', 'origin', remote, cwd=work)
		if token:
			os.environ['GH_TOKEN'] = token
		configure_auth()
		publish_source(work, selected, remote, queue, refs.get('refs/heads/main', ''))
		check_fresh(UPSTREAM, selected, remote, queue, refs.get('refs/heads/main', ''))
		git('push', '--atomic',
			'--force-with-lease=refs/heads/main:' + refs.get('refs/heads/main', ''),
			'origin', 'HEAD:refs/heads/main', cwd=work)


if __name__ == '__main__':
	if len(sys.argv) == 3 and sys.argv[1] in ('prepare', 'promote'):
		refresh(sys.argv[1], Path(sys.argv[2]).resolve())
	else:
		main()
