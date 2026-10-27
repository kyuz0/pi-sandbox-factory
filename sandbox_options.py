"""Validated, shared settings for the CLI, cockpit and container bootstrap."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

SKILLS = {}
PROFILE_SKILLS = {'base': []}
DEFAULTS = {'approval': 'automatic', 'inner_sandbox': True, 'goals': True,
            'scheduling': True, 'browser': False, 'disabled_skills': [], 'burp_url': '', 'burp_transport': 'sse'}


def options(value=None):
    value = value or {}
    if not isinstance(value, dict) or set(value) - DEFAULTS.keys():
        raise ValueError('Unknown sandbox options')
    result = {**DEFAULTS, **value}
    if result['approval'] not in ('automatic', 'manual', 'off'):
        raise ValueError('Approval must be automatic, manual or off')
    for key in ('inner_sandbox', 'goals', 'scheduling', 'browser'):
        if type(result[key]) is not bool:
            raise ValueError(key + ' must be a boolean')
    disabled = result['disabled_skills']
    if not isinstance(disabled, list) or any(x not in SKILLS for x in disabled):
        raise ValueError('Unknown disabled skill')
    if result['burp_transport'] not in ('sse', 'http'):
        raise ValueError('Burp transport must be sse or http')
    if not isinstance(result['burp_url'], str):
        raise ValueError('Burp URL must be a string')
    if result['burp_url']:
        endpoint_rule(result['burp_url'])
    return result


def endpoint_rule(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or any(c.isspace() for c in url)):
        raise ValueError('Use an HTTP(S) endpoint without credentials or fragments')
    return f'{parsed.hostname}:{parsed.port or (443 if parsed.scheme == "https" else 80)}'


def memory_limit(value):
    if value in (None, '', 'none'):
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*[bBkKmMgG]?', value):
        raise ValueError('Memory must be a positive size such as 8g, or none')
    return value


def permissions(template, selected):
    selected = options(selected)
    policy = json.loads(json.dumps(template))
    policy['authorizerChain'] = ['pi-auto-review'] if selected['approval'] == 'automatic' else []
    rules = policy['permission']
    rules['bash'] = ('allow' if selected['inner_sandbox'] or selected['approval'] == 'off' else 'ask')
    if selected['approval'] == 'off':
        rules.update({'*': 'allow', 'external_directory': 'allow'})
    return policy


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.new')
    # Never follow a pre-existing temporary symlink.
    temporary.unlink(missing_ok=True)
    with temporary.open('x') as stream:
        temporary.chmod(0o600)
        json.dump(value, stream, indent=2)
        stream.write('\n')
    temporary.replace(path)


def guidance(selected, subagents=False):
    selected = options(selected)
    mode, inner = selected['approval'], selected['inner_sandbox']
    lines = ['Work inside the devcontainer. The selected outer network policy always applies.']
    if inner:
        lines.append('Ordinary bash runs inside the inner OS sandbox without command-level model review. '
                     'Workspace edits are allowed; private home and security configuration are protected.')
        lines.append({'automatic': 'Boundary requests use the current-model reviewer. Use bash_escalate with an exact command and justification when access outside the inner sandbox is required.',
                      'manual': 'Boundary requests require human approval. Use bash_escalate with an exact command and justification when access outside the inner sandbox is required.',
                      'off': 'Approval prompts are disabled. Requests beyond the inner sandbox are refused; bash_escalate is unavailable.'}[mode])
    else:
        lines.append('The inner command sandbox is disabled. Bash executes inside the outer devcontainer. '
                     + {'automatic': 'Shell commands require current-model automatic review.',
                        'manual': 'Shell commands require human approval.',
                        'off': 'Approval prompts are disabled; commands execute directly.'}[mode])
    lines.append('Explicit permission denials must be respected. Commands cannot execute on the physical host. '
                 'Use inherited proxy settings in restricted network mode.')
    lines.append('Standard pi-subagents are enabled with the same selected capabilities and approval rules.' if subagents
                 else 'Subagents are disabled. Work in the current agent; do not start extra Pi processes for delegation.')
    if selected['goals']:
        lines.append('Goal mode is available through /goal and create_goal. Start a goal only when explicitly requested.')
    if selected['scheduling']:
        lines.append('Use schedule_prompt for requested future or recurring prompts. Jobs inject into this chat, '
                     'with its model and approval rules. Timers run only while this Pi session is open; '
                     'never promise delivery while Pi or the container is stopped. /schedule-prompt manages jobs.')
    return '\n\n'.join(lines) + '\n'
