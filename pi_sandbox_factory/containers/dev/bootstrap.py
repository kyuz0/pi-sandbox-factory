"""Initialize private Pi configuration, optionally seeded from shared resources."""
import json
import os
from pathlib import Path
import shutil
import subprocess

os.umask(0o077)
agent = Path('/home/node/.pi/agent')
agent.mkdir(parents=True, exist_ok=True, mode=0o700)
shared = Path('/pi-config')
for source in sorted(shared.iterdir()):
    # Recovery journals and locks describe a host-side transaction, not this sandbox.
    if source.name.startswith('models.json.'):
        continue
    # Sessions, OAuth refreshes, trust decisions, and settings need writable storage.
    if source.name in {'sessions', 'models.json',
                       'auth.json', 'web-search.json', 'settings.json', 'trust.json', 'APPEND_SYSTEM.md', 'pendant-goals.json'}:
        target = agent / source.name
        # Migrate writable configuration links created by older versions.
        migrate = (source.name in {'models.json', 'web-search.json', 'APPEND_SYSTEM.md'} and target.is_symlink()
                   and target.readlink() == source)
        if source.is_file() and (not target.exists() or migrate):
            temporary = agent / ('.' + source.name + '.seed')
            shutil.copyfile(source, temporary)
            temporary.chmod(0o600)
            temporary.replace(target)
        continue
    target = agent / source.name
    if not target.exists() and not target.is_symlink():
        target.symlink_to(source, target_is_directory=source.is_dir())

for filename, contents in (('models.json', {'providers': {}}), ('settings.json', {})):
    target = agent / filename
    if not target.exists() and not target.is_symlink():
        target.write_text(json.dumps(contents, indent=2) + '\n')
        target.chmod(0o600)

# Launcher-managed feature selections are read-only runtime inputs.
selection_file = Path('/opt/sandbox/options.json')
selection = json.loads(selection_file.read_text()) if selection_file.exists() else {}
approval = selection.get('approval', 'automatic')
inner_sandbox = selection.get('inner_sandbox', True)
goals_enabled = selection.get('goals', True)
scheduling_enabled = selection.get('scheduling', True)
browser_enabled = selection.get('browser', False)

# Register installed resources through Pi's native configuration.
settings_file = agent / 'settings.json'
settings = json.loads(settings_file.read_text())
# Replace legacy registrations with the image-managed versions. Pi rejects
# duplicate Bash tools; a raw scheduler would expose an independent-agent path.
managed_packages = ('pi-sandbox', '@erichll/pi-sandbox', '@erichll/pi-auto-review',
                    '@gotgenes/pi-permission-system', 'pi-goal', 'pi-schedule-prompt', 'betterwright', 'pi-web-access', '@juicesharp/rpiv-ask-user-question')

def managed_package(resource):
    source = resource.get('source') if isinstance(resource, dict) else resource
    return isinstance(source, str) and any(
        source == 'npm:' + name or source.startswith('npm:' + name + '@')
        for name in managed_packages)

if 'packages' in settings:
    settings['packages'] = [p for p in settings['packages'] if not managed_package(p)]

subagents_enabled = os.environ.get('SANDBOX_SUBAGENTS') == '1'
subagent_extensions = [('/opt/pi-security/packages/pi-sandbox/src/container-child-policy.ts' if selection else '/opt/pi-security/packages/pi-sandbox/src/container-subagents.ts'),
                       '/opt/pi-security/node_modules/pi-subagents/index.js']
# Migrate both versions of the required child policy when toggling settings.
settings['extensions'] = [p for p in settings.get('extensions', []) if p not in
    ('/opt/pi-security/child-policy.ts', '/opt/pi-security/packages/pi-sandbox/src/container-child-policy.ts', '/opt/pi-security/packages/pi-sandbox/src/container-subagents.ts')]
# Remove only launcher-managed registrations when the saved choice is disabled.
if not subagents_enabled:
    settings['extensions'] = [p for p in settings.get('extensions', []) if p not in subagent_extensions]
    if isinstance(settings.get('subagents'), dict):
        scans = settings['subagents'].get('agentScanDirs', [])
        settings['subagents']['agentScanDirs'] = [p for p in scans if p != '/opt/pi-security/agents']
image_resources = {
    'extensions': [
                   '/opt/rpiv-ask-user-question/index.ts',
                   '/opt/pi-security/packages/pi-auto-review/src/index.ts',
                   '/opt/pi-security/node_modules/@gotgenes/pi-permission-system/src/index.ts',
                   '/opt/pi-security/packages/pi-reviewed-escalation/index.ts',
                   '/opt/pi-security/packages/pi-sandbox/src/index.ts',
                   '/opt/pi-security/packages/pi-session-schedule/index.mjs']
                  + (subagent_extensions if subagents_enabled else []),
    'skills': [],
}
# Profiles may register image-local resources without carrying user configuration.
profile_resources = Path('/opt/sandbox/resources.json')
for resource_file in (profile_resources, Path('/opt/sandbox/extra-resources.json'), Path('/opt/sandbox/provider-resources.json')):
    if not resource_file.exists():
        continue
    for key, resources in json.loads(resource_file.read_text()).items():
        if key not in {'skills', 'prompts', 'extensions'} or not isinstance(resources, list):
            raise ValueError('Invalid profile resource declaration')
        for resource in resources:
            path = Path(resource)
            if not path.is_absolute() or not path.resolve().is_relative_to('/opt'):
                raise ValueError('Profile resources must live under /opt')
        image_resources.setdefault(key, []).extend(resources)
settings['skills'] = [p for p in settings.get('skills', []) if not isinstance(p, str) or not p.startswith('/opt/extra-skills/')]
# Remove only registrations owned by this launcher, then apply the saved choice.
# Remember registrations across profile/provider changes, removing only our previous entries.
resource_state=agent/'sandbox-resources.json'
previous=json.loads(resource_state.read_text()) if resource_state.exists() else {}
managed = {key: set(values) | set(previous.get(key, [])) for key, values in image_resources.items()}
managed['extensions'].add('/opt/pi-local-model-manager/extensions/local-models.js')
if not Path('/opt/sandbox/provider-resources.json').exists():
    image_resources['extensions'].append('/opt/pi-local-model-manager/extensions/local-models.js')
resource_state.write_text(json.dumps(image_resources))
resource_state.chmod(0o600)
managed['extensions'].add('/opt/pi-security/node_modules/pi-goal/.pi/extensions/pi-goal/index.ts')
managed['skills'].add('/opt/pi-security/node_modules/pi-goal/skills')
managed['extensions'].add('/opt/pi-advisor/extensions/advisor.js')
managed['skills'].add('/opt/pi-advisor/skills/advisor')
managed['extensions'].update(['/opt/pi-security/approval-mode.ts', '/opt/pi-security/packages/pi-auto-review/src/container-approval-mode.ts'])
managed['extensions'].add('/opt/betterwright/extension.mjs')
managed['extensions'].add('/opt/pi-web-access/node_modules/pi-web-access/dist/index.js')
web_extension = '/opt/pi-web-access/extension.mjs'
managed['extensions'].add(web_extension)
for key, values in managed.items():
    settings[key] = [p for p in settings.get(key, []) if not isinstance(p, str) or p not in values]
if os.environ.get('PI_ADVISOR_SOCKET'):
    image_resources['extensions'].append('/opt/pi-advisor/extensions/advisor.js')
    image_resources['skills'].append('/opt/pi-advisor/skills/advisor')
if (selection.get('web_access') or {}).get('enabled'):
    if not Path(web_extension).is_file():
        raise ValueError('Web access is enabled but absent from this image; recreate the sandbox')
    image_resources['extensions'].append(web_extension)
    subprocess.run(['python3', '/usr/local/lib/sandbox-web-access.py'], check=True)
if browser_enabled:
    if not Path('/opt/betterwright/extension.mjs').is_file():
        raise ValueError('Betterwright is enabled but missing from this image; recreate with --browser')
    image_resources['extensions'].append('/opt/betterwright/extension.mjs')
if approval not in ('automatic', 'assisted'):
    image_resources['extensions'].remove('/opt/pi-security/packages/pi-auto-review/src/index.ts')
    image_resources['extensions'].insert(0, '/opt/pi-security/packages/pi-auto-review/src/container-approval-mode.ts')
if not inner_sandbox:
    image_resources['extensions'].remove('/opt/pi-security/packages/pi-sandbox/src/index.ts')
if not inner_sandbox or approval == 'off':
    image_resources['extensions'].remove('/opt/pi-security/packages/pi-reviewed-escalation/index.ts')
if not scheduling_enabled:
    image_resources['extensions'].remove('/opt/pi-security/packages/pi-session-schedule/index.mjs')
for key, resources in image_resources.items():
    paths = settings.setdefault(key, [])
    for resource in resources:
        if Path(resource).exists() and resource not in paths:
            paths.append(resource)
if subagents_enabled and Path(subagent_extensions[-1]).exists():
    subagents = settings.setdefault('subagents', {})
    subagents.setdefault('toolActivation', 'eager')
    scan_dirs = subagents.setdefault('agentScanDirs', [])
    if '/opt/pi-security/agents' not in scan_dirs:
        scan_dirs.append('/opt/pi-security/agents')
settings_file.write_text(json.dumps(settings, indent=2) + '\n')

# The launcher Goals switch controls Pendant's built-in goals.
goal_file = agent / 'pendant-goals.json'
goal_settings = json.loads(goal_file.read_text()) if goal_file.exists() else {}
goal_settings['enabled'] = goals_enabled
temporary = agent / '.pendant-goals.json.new'
temporary.unlink(missing_ok=True)
temporary.write_text(json.dumps(goal_settings, indent=2) + '\n')
temporary.chmod(0o600)
temporary.replace(goal_file)

# Pi natively reads this file; preserve user instructions around the managed block.
profile = Path('/opt/sandbox/profile.md')
append_file = agent / 'APPEND_SYSTEM.md'
begin, end = '<!-- sandbox-profile -->', '<!-- /sandbox-profile -->'
contents = append_file.read_text() if append_file.exists() else ''
if begin in contents and end in contents:
    start = contents.index(begin)
    finish = contents.index(end, start) + len(end)
    contents = contents[:start] + contents[finish:]
if profile.exists():
    guidance = profile.read_text().rstrip()
    for common in ('document-tools.md', 'security.md'):
        extra = (Path('/opt/pi-security/config/security.md') if selection and common == 'security.md'
                 else Path('/opt/sandbox') / common)
        if extra.exists():
            guidance += '\n\n' + extra.read_text().rstrip()
    if selection:
        guidance += ('\n\nSaved agent settings: approval=' + approval
                     + ', inner sandbox=' + str(inner_sandbox)
                     + ', goals=' + str(goals_enabled) + ', scheduling=' + str(scheduling_enabled)
                     + '. These saved settings override generic feature descriptions above. '
                     + 'Only use tools and skills actually present in this session.')
    if browser_enabled:
        guidance += '\n\n' + Path('/opt/betterwright/browser.md').read_text().rstrip()
    contents = contents.rstrip() + '\n\n' + begin + '\n' + guidance + '\n' + end + '\n'
if contents or append_file.exists():
    append_file.write_text(contents)

for server in ('.vscode-server', '.vscode-server-insiders'):
    base = Path('/home/node') / server
    extensions = base / 'extensions'
    extensions.mkdir(parents=True, exist_ok=True)
    for source in Path('/opt/pendant').iterdir():
        target = extensions / source.name
        if not target.exists():
            shutil.copytree(source, target)
    machine = base / 'data/Machine/settings.json'
    machine.parent.mkdir(parents=True, exist_ok=True)
    settings = json.loads(machine.read_text()) if machine.exists() else {}
    # Pendant embeds Pi; these removed settings no longer select a runtime.
    for obsolete in ('pendant.runtimeSource', 'pendant.binaryPath', 'pendant.nodePath'):
        settings.pop(obsolete, None)
    settings.update({
        'pendant.agentDir': str(agent),
        'python.defaultInterpreterPath': (os.environ['VIRTUAL_ENV'] + '/bin/python'
                                          if os.environ.get('VIRTUAL_ENV') else '/usr/bin/python3'),
        'http.proxy': ('http://127.0.0.1:3128' if os.environ.get('SANDBOX_NETWORK_MODE') != 'unrestricted' else ''),
        'http.proxySupport': ('override' if os.environ.get('SANDBOX_NETWORK_MODE') != 'unrestricted' else 'off'),
        'git.terminalAuthentication': False,
    })
    if browser_enabled:
        # Match the Chromium process, leaving application port forwarding intact.
        settings.setdefault('remote.portsAttributes', {})[r'(^|/)betterchromium(?:\s|$)'] = {
            'onAutoForward': 'ignore', 'label': 'Sandbox browser (use viewer)',
        }
    machine.write_text(json.dumps(settings, indent=2) + '\n')

# The launcher owns the approved host and port selection; preserve other discovery preferences.
if os.environ.get('LOCAL_MODEL_PORTS'):
    discovery = agent / 'local-pi-models.json'
    value = json.loads(discovery.read_text()) if discovery.exists() else {}
    value.update(host='local-model.internal', ports=os.environ['LOCAL_MODEL_PORTS'])
    temporary = discovery.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    temporary.chmod(0o600)
    temporary.replace(discovery)
