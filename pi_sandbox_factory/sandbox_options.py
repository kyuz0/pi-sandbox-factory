"""Validated, shared settings for the CLI, cockpit and container bootstrap."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from . import web_access, network_groups, communications

SKILLS = {}
PROFILE_SKILLS = {'base': []}
DEFAULTS = {'approval': 'automatic', 'inner_sandbox': True, 'goals': True,
            'scheduling': True, 'question_forms': True, 'browser': False,
            'protect_credentials': True, 'compaction_recall': 'lite',
            'disabled_skills': [], 'web_access': None, 'website_groups': [], 'communications': None}

COMMON_CREDENTIAL_PATTERNS = ('*.pem', '*.key', '*.env', '*.env.*')


def options(value=None):
    value = value or {}
    if not isinstance(value, dict) or set(value) - DEFAULTS.keys():
        raise ValueError('Unknown sandbox options')
    result = {**DEFAULTS, **value}
    if result['approval'] not in ('automatic', 'assisted', 'manual', 'off'):
        raise ValueError('Approval must be automatic, assisted, manual or off')
    for key in ('inner_sandbox', 'goals', 'scheduling', 'question_forms', 'browser', 'protect_credentials'):
        if type(result[key]) is not bool:
            raise ValueError(key + ' must be a boolean')
    if result['compaction_recall'] not in ('lite', 'full', 'off'):
        raise ValueError('Conversation recall must be lite, full or off')
    disabled = result['disabled_skills']
    if not isinstance(disabled, list) or any(x not in SKILLS for x in disabled):
        raise ValueError('Unknown disabled skill')
    result['web_access'] = web_access.settings(result['web_access'])
    result['communications'] = communications.settings(result['communications'])
    result['website_groups'] = network_groups.selected(result['website_groups'])
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
    policy['authorizerChain'] = ['pi-auto-review'] if selected['approval'] in ('automatic', 'assisted') else []
    rules = policy['permission']
    if not selected['protect_credentials']:
        paths = rules.get('path')
        if isinstance(paths, dict):
            for pattern in COMMON_CREDENTIAL_PATTERNS:
                if paths.get(pattern) == 'deny':
                    paths.pop(pattern)
    # Native read tools already admit these trusted image paths. Give proven
    # shell reads the same scope; unknown effects and writes still need review.
    reads = rules.setdefault('external_directory_read', {})
    for path in policy.get('piInfrastructureReadPaths', []) if isinstance(reads, dict) else []:
        if path.startswith('/') and not any(c in path for c in '*?'):
            reads.setdefault(path.rstrip('/'), 'allow')
            reads.setdefault(path.rstrip('/') + '/*', 'allow')
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
        lines.append({'assisted': 'Boundary requests use automatic review with human fallback. Use bash_escalate for an exact reviewed command.',
                      'automatic': 'Boundary requests use the current-model reviewer without human approval dialogs. Review failures return a reason; retry the review or choose an allowed alternative without bypassing a rejection. Use bash_escalate with an exact command and justification when access outside the inner sandbox is required.',
                      'manual': 'Boundary requests require human approval. Use bash_escalate with an exact command and justification when access outside the inner sandbox is required.',
                      'off': 'Approval prompts are disabled. Requests beyond the inner sandbox are refused; bash_escalate is unavailable.'}[mode])
    else:
        lines.append('The inner command sandbox is disabled. Bash executes inside the outer devcontainer. '
                     + {'automatic': 'Shell commands require automatic review without human approval dialogs. Failures return a reason to the agent.',
                        'assisted': 'Shell commands use automatic review with human fallback.',
                        'manual': 'Shell commands require human approval.',
                        'off': 'Approval prompts are disabled; commands execute directly.'}[mode])
    if inner:
        credential_text = ('Common credential files such as .env and private keys are protected from agent reads.'
                           if selected['protect_credentials'] else
                           'The agent may read and write common credential files such as .env and private keys in the workspace. '
                           'Their contents are visible to the model and the agent may change them.')
        lines.append('Read installed skill instructions and references with read, grep, find or ls. '
                     'Read-only shell commands can also read the trusted installed tool and skill directories. '
                     'This does not permit changing those files. ' + credential_text)
        lines.append('Each bash call has its own temporary directory in $TMPDIR, removed when the call ends. '
                     'Keep files needed by later calls in the workspace, for example .tmp/.')
        if mode != 'off':
            lines.append('The inner sandbox blocks Unix sockets, which tmux needs. '
                         'Use bash_escalate for tmux creation, send-keys, capture-pane, session checks and cleanup. '
                         "Use tmux -S with the session's socket path on every call. "
                         'Do not retry tmux in ordinary bash or change socket directories to work around the restriction. '
                         'The reviewer must approve the exact outer-container command; a denial still stops it.')
        else:
            lines.append('tmux cannot run in the inner sandbox because Unix sockets are blocked. '
                         'bash_escalate is unavailable with approval disabled; ask the user to select an approval mode if tmux is needed.')
    if inner:
        lines.append('For network commands in bash, keep the inherited proxy settings. '
                     'Outbound connections are reviewed and the outer network allowlist still applies. '
                     'Container-local services, including the inference proxy on outer-container loopback, '
                     'may require bash_escalate because the inner shell has a separate network namespace. '
                     'Escalation does not add destinations to the outer allowlist or reveal provider keys.')
    if selected['browser']:
        lines.append('Use the native browser tool for Playwright automation; do not launch a separate browser through bash.')
    lines.append('Explicit permission denials must be respected. Commands cannot execute on the physical host. '
                 'Use inherited proxy settings in restricted network mode.')
    lines.append('Standard pi-subagents are enabled with the same selected capabilities and approval rules.' if subagents
                 else 'Subagents are disabled. Work in the current agent; do not start extra Pi processes for delegation.')
    if selected['goals']:
        lines.append('Pendant provides built-in goals. Start a goal only when explicitly requested and the goal tools are present.')
    if selected['scheduling']:
        lines.append('Use schedule_prompt for requested future or recurring prompts. Jobs inject into this chat, '
                     'with its model and approval rules. Timers run only while this Pi session is open; '
                     'never promise delivery while Pi or the container is stopped. /schedule-prompt manages jobs.')
    lines.append(web_access.guidance(selected['web_access']))
    return '\n\n'.join(x for x in lines if x) + '\n'
