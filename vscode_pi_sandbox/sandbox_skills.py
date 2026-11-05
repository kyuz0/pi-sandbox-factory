"""Snapshot additional remote skills outside the checkout and build them into images."""
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.parse import urlsplit


def validate_source(repo, folder):
    if (not isinstance(repo, str) or not repo or repo.startswith('-') or any(c.isspace() for c in repo)
            or not (repo.startswith(('https://', 'ssh://', 'git@')))):
        raise ValueError('Use an HTTPS or SSH Git repository URL for the additional skill')
    if repo.startswith(('https://', 'ssh://')):
        parsed = urlsplit(repo)
        if not parsed.hostname or parsed.password or (parsed.scheme == 'https' and parsed.username):
            raise ValueError('Git URLs must not contain embedded credentials')
    path = PurePosixPath(folder)
    if not folder or path.is_absolute() or '..' in path.parts or ':' in folder or '\\' in folder:
        raise ValueError('Use a relative skill folder within the repository')
    return path


def snapshot(repo, folder, state, launcher):
    relative = validate_source(repo, folder)
    with tempfile.TemporaryDirectory(prefix='.skill-', dir=state) as temp:
        checkout = Path(temp) / 'checkout'
        launcher.run(['git', 'clone', '--recurse-submodules', '--', repo, str(checkout)])
        launcher.tree_digest(checkout)
        selected = checkout / relative
        if not (selected / 'SKILL.md').is_file():
            raise ValueError('The selected folder does not contain SKILL.md')
        # Read only the native skill name, never execute repository metadata.
        match = re.search(r'^name:\s*[\'"]?([a-z0-9][a-z0-9-]*)[\'"]?\s*$',
                          (selected / 'SKILL.md').read_text(), re.M)
        if not match:
            raise ValueError('SKILL.md needs a lowercase name in its frontmatter')
        from .sandbox_options import SKILLS
        if match[1] in SKILLS or match[1] == 'goal':
            raise ValueError('That skill is managed by a built-in profile; use its profile settings')
        revision = launcher.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], capture=True).stdout.strip()
        digest = launcher.tree_digest(selected)
        target = state / 'skills' / digest
        if not target.exists():
            target.parent.mkdir(exist_ok=True)
            shutil.copytree(selected, target, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        return {'name': match[1], 'repo': repo, 'folder': folder, 'commit': revision,
                'digest': digest, 'path': str(target)}


def build(config, image, launcher, base_image=None):
    skills = config.get('extra_skills', [])
    if not skills:
        return
    with tempfile.TemporaryDirectory(prefix='vscode-pi-sandbox-skills-') as temp:
        context = Path(temp)
        resources = []
        for skill in skills:
            source = Path(skill['path'])
            if launcher.tree_digest(source) != skill['digest']:
                raise ValueError('Additional skill snapshot was modified; add its remote source again')
            shutil.copytree(source, context / skill['name'])
            resources.append('/opt/extra-skills/' + skill['name'])
        (context / 'extra-resources.json').write_text(json.dumps({'skills': resources}))
        (context / 'Dockerfile').write_text('ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\nUSER root\n'
            + ''.join('COPY ' + s['name'] + '/ /opt/extra-skills/' + s['name'] + '/\n' for s in skills)
            + 'COPY extra-resources.json /opt/sandbox/extra-resources.json\n'
              'RUN chmod -R a+rX /opt/extra-skills\nUSER node\n')
        launcher.run([config['engine'], 'build', '-t', image, '--build-arg', 'BASE_IMAGE=' + (base_image or image), context])
