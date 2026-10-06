#!/usr/bin/env python3
"""Reconstruct official master plus ordered fork patches; never modify automation."""
import base64
import os
import shutil
from pathlib import Path
import subprocess
import tempfile


def git(*args, cwd=None):
	return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def reconstruct(upstream, tooling, destination):
	git('clone', '--quiet', '--no-checkout', upstream, str(destination))
	git('checkout', '--quiet', '--detach', 'origin/master', cwd=destination)
	base = git('rev-parse', 'HEAD', cwd=destination)
	for patch in sorted((tooling / 'patches').glob('*.patch')):
		path = str(patch.resolve())
		check = subprocess.run(['git', 'apply', '--check', path], cwd=destination,
			stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		if check.returncode == 0:
			git('apply', path, cwd=destination)
		else:
			# Upstream may absorb a patch; only an exact reverse check proves it.
			git('apply', '--reverse', '--check', path, cwd=destination)
			print('Already included upstream: ' + patch.name)
	readme = destination / 'README.md'
	readme.write_bytes((tooling / 'README-prefix.md').read_bytes() + readme.read_bytes())
	# Keep inherited workflows out of generated main, without changing upstream.
	git('rm', '-r', '--ignore-unmatch', '.github/workflows', cwd=destination)
	shutil.copytree(tooling, destination / '.downstream')
	git('add', '-A', cwd=destination)
	git('-c', 'user.name=Nitrox Fork', '-c', 'user.email=actions@felixfoertsch.de',
		'commit', '--quiet', '-m', 'Apply Nitrox fork patches [skip ci]', cwd=destination)
	git('merge-base', '--is-ancestor', base, 'HEAD', cwd=destination)
	return base


def main():
	if git('status', '--porcelain'):
		raise SystemExit('Working tree must be clean')
	tooling = Path(__file__).resolve().parent
	remote = git('remote', 'get-url', 'origin')
	# Exact leases protect concurrent source and tooling edits.
	refs = dict((ref, sha) for sha, ref in
		(line.split() for line in git('ls-remote', '--heads', 'origin').splitlines()))
	automation = git('rev-parse', 'HEAD')
	if refs.get('refs/heads/automation') != automation:
		raise SystemExit('HEAD must match published automation')
	with tempfile.TemporaryDirectory() as tmp:
		work = Path(tmp) / 'source'
		reconstruct('https://github.com/SubnauticaNitrox/Nitrox.git', tooling, work)
		if git('ls-remote', remote, 'refs/heads/automation').split()[0] != automation:
			raise SystemExit('Automation changed during patch replay')
		git('remote', 'set-url', 'origin', remote, cwd=work)
		# New clone does not inherit checkout's HTTP credentials. Generated main
		# has no workflows, so the automatic job token can publish it.
		if os.environ.get('GITHUB_ACTIONS') == 'true':
			token = os.environ.get('GH_TOKEN')
			if not token:
				raise SystemExit('GH_TOKEN is required in GitHub Actions')
			auth = base64.b64encode(('x-access-token:' + token).encode()).decode()
			print('::add-mask::' + auth, flush=True)
			os.environ.update(GIT_CONFIG_COUNT='1',
				GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
				GIT_CONFIG_VALUE_0='AUTHORIZATION: basic ' + auth)
		git('push', '--atomic',
			'--force-with-lease=refs/heads/main:' + refs.get('refs/heads/main', ''),
			'origin', 'HEAD:refs/heads/main', cwd=work)


if __name__ == '__main__':
	main()
