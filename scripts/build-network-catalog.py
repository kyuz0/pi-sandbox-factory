#!/usr/bin/env python3
"""Build positive category snapshots from downloaded, pinned upstream sources."""
import argparse
import json
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pi_sandbox_factory.network_groups import domain, expand_v2fly

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--v2fly', type=Path, required=True, help='Pinned domain-list-community checkout')
parser.add_argument('--ut1', type=Path, required=True, help='Folder with press, financial, bank and liste_bu domain files')
parser.add_argument('--v2fly-revision', required=True)
parser.add_argument('--ut1-revision', required=True)
args = parser.parse_args()

def checked(values):
    output, skipped = set(), []
    for value in values:
        try:
            rule = domain(value)
            output.add(rule)
        except ValueError:
            skipped.append(value)
    return sorted(output), sorted(skipped)


def expand(name):
    return expand_v2fly(name, lambda key: (args.v2fly / 'data' / key).read_text())


groups = {}
for name, title, description in [
    ('python', 'Python', 'Python documentation, PyPI and hosted Python projects.'),
    ('npmjs', 'npm', 'The npm package registry and community sites.'),
    ('rust', 'Rust', 'Rust documentation, crates and package downloads.'),
    ('github', 'GitHub', 'Repositories, APIs, downloads, Copilot, npm and shared GitHub Pages. Includes user-published content.'),
    ('stackexchange', 'Stack Exchange', 'Stack Overflow and the Stack Exchange network, including community posts.'),
    ('readthedocs', 'Read the Docs', 'Documentation hosted on Read the Docs, including user-published projects.'),
]:
    domains, skipped = checked(expand(name))
    if skipped:
        raise ValueError(f'{name}: review rejected entries: {skipped}')
    groups['dev-' + name] = {'title': title, 'description': description,
        'source': 'V2Fly domain-list-community', 'url': 'https://github.com/v2fly/domain-list-community',
        'revision': args.v2fly_revision, 'license': 'MIT', 'domains': domains}
for name, title, description in [
    ('press', 'News and press', 'News publishers in the UT1 press category.'),
    ('financial', 'Financial information', 'Financial news and information sites in the UT1 financial category.'),
    ('bank', 'Banking', 'Online banking domains in the UT1 bank category.'),
    ('liste_bu', 'Library resources', 'Library, academic and government resources selected by UT1, oriented towards its French university library.'),
]:
    domains, skipped = checked('.' + s.strip() for s in (args.ut1 / name).read_text().splitlines() if s.strip())
    groups['ut1-' + name] = {'title': title, 'description': description,
        'source': 'Université Toulouse Capitole (UT1)', 'url': 'https://dsi.ut-capitole.fr/blacklists/',
        'revision': args.ut1_revision, 'license': 'CC-BY-SA-4.0',
        'note': 'Category coverage and maintenance vary. This is a topic list, not a security rating.',
        'omitted_entries': skipped, 'domains': domains}
out = Path(__file__).resolve().parents[1] / 'pi_sandbox_factory/network-catalog'
out.mkdir(exist_ok=True)
(out / 'groups.json').write_text(json.dumps({'groups': groups}, indent=2, ensure_ascii=True) + '\n')
for name, group in groups.items():
    print(name, len(group['domains']), 'domains;', len(group.get('omitted_entries', [])), 'omitted')
