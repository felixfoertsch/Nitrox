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

UPSTREAM = 'https://github.com/SubnauticaNitrox/Nitrox.git'


def git(*args, cwd=None):
	return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def selection(upstream):
	lines = git('ls-remote', '--symref', upstream, 'HEAD').splitlines()
	branch = next(line.split()[1] for line in lines if line.startswith('ref:'))
	nightly = next(line.split()[0] for line in lines if line.endswith('\tHEAD') and not line.startswith('ref:'))
	return branch, nightly


def reconstruct(upstream, tooling, destination, revision=None):
	git('clone', '--quiet', '--no-checkout', upstream, str(destination))
	git('checkout', '--quiet', '--detach', revision or 'origin/HEAD', cwd=destination)
	base = git('rev-parse', 'HEAD', cwd=destination)
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
	git('add', '-A', cwd=destination)
	date = git('show', '-s', '--format=%cI', base, cwd=destination)
	env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
	subprocess.run(['git', '-c', 'user.name=Nitrox Fork', '-c', 'user.email=actions@felixfoertsch.de',
		'-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'apply Nitrox fork patches [skip ci]'],
		cwd=destination, env=env, check=True)
	git('merge-base', '--is-ancestor', base, 'HEAD', cwd=destination)
	return base


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
	if os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and refs.get('refs/heads/main'):
		git('fetch', '--quiet', remote, refs['refs/heads/main'])
		if upstream_unchanged('schedule', git('rev-parse', refs['refs/heads/main'] + '^'), selected):
			print('Upstream unchanged; synchronization skipped')
			return
	with tempfile.TemporaryDirectory() as tmp:
		root = Path(tmp)
		work = root / 'nightly'
		reconstruct(UPSTREAM, tooling, work, selected[1])
		check_fresh(UPSTREAM, selected, remote, queue, refs.get('refs/heads/main', ''))
		git('remote', 'set-url', 'origin', remote, cwd=work)
		if os.environ.get('GITHUB_ACTIONS') == 'true':
			token = os.environ.get('GH_TOKEN')
			if not token:
				raise SystemExit('GH_TOKEN is required in GitHub Actions')
			auth = base64.b64encode(('x-access-token:' + token).encode()).decode()
			print('::add-mask::' + auth, flush=True)
			os.environ.update(GIT_CONFIG_COUNT='1',
				GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
				GIT_CONFIG_VALUE_0='AUTHORIZATION: basic ' + auth)
		publish_source(work, selected, remote, queue, refs.get('refs/heads/main', ''))
		check_fresh(UPSTREAM, selected, remote, queue, refs.get('refs/heads/main', ''))
		git('push', '--atomic',
			'--force-with-lease=refs/heads/main:' + refs.get('refs/heads/main', ''),
			'origin', 'HEAD:refs/heads/main', cwd=work)


if __name__ == '__main__':
	main()
