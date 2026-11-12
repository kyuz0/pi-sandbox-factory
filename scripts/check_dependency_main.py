"""Require Factory's pinned Git dependencies to be ancestors of their main branch."""
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request


def dependency_pins(root):
    pins = {}
    def add(repository, commit):
        match = re.fullmatch(r'https://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?', repository)
        if not match or not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError('Git dependencies require a GitHub repository and full commit SHA')
        name = match[1]
        if name in pins and pins[name] != commit:
            raise ValueError('Conflicting dependency pins: ' + name)
        pins[name] = commit
    dev = root / 'pi_sandbox_factory/containers/dev'
    for entry in json.loads((dev/'extensions.lock.json').read_text())['extensions'].values():
        add(entry['repository'], entry['commit'])
    for entry in json.loads((dev/'security/sources.json').read_text()).values():
        match = re.fullmatch(r'https://codeload\.github\.com/([\w.-]+/[\w.-]+)/tar\.gz/([0-9a-f]{40})', entry['url'])
        if not match or match[2] != entry['commit']:
            raise ValueError('Source archive URL does not match its pinned commit')
        add('https://github.com/' + match[1], entry['commit'])
    for filename in ('package.json', 'package-lock.json'):
        data = json.loads((dev/'communications'/filename).read_text())
        values = list(data.get('dependencies', {}).values())
        values += [p.get('resolved') for p in data.get('packages', {}).values()]
        for value in values:
            if not isinstance(value, str):
                continue
            match = re.fullmatch(r'https://github\.com/([\w.-]+/[\w.-]+)/archive/([0-9a-f]{40})\.tar\.gz', value)
            if match:
                add('https://github.com/' + match[1], match[2])
            elif value.startswith('https://github.com/'):
                raise ValueError('Git archive dependency requires a full commit SHA')
    return pins


def check_main(pins, fetch):
    for repository, commit in sorted(pins.items()):
        comparison = fetch(f'https://api.github.com/repos/{repository}/compare/{commit}...main')
        if comparison.get('status') not in ('ahead', 'identical'):
            raise ValueError(f'{repository}: {commit} is not on main; merge and test the dependency before publishing Factory')
        print(repository + ': ' + commit + ' is on main')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    def fetch(url):
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'pi-sandbox-factory-dependency-check'}
        token = os.environ.get('GITHUB_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
            return json.load(response)
    check_main(dependency_pins(args.root), fetch)


if __name__ == '__main__':
    main()
