"""Positive website categories, refreshed from their selected upstream sources."""
import copy
import ipaddress
import json
from pathlib import Path
import re
import os
import time
import tempfile
from functools import lru_cache
from urllib.request import urlopen

CATALOG = Path(__file__).with_name('network-catalog') / 'groups.json'
PRIVATE_RANGES = ('0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 '
                  '169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 '
                  '192.168.0.0/16 198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 '
                  '224.0.0.0/4 240.0.0.0/4 ::/128 ::1/128 ::ffff:0:0/96 '
                  '64:ff9b::/96 100::/64 2001:db8::/32 fc00::/7 fe80::/10 ff00::/8')


@lru_cache(maxsize=1)
def catalog():
    return json.loads(CATALOG.read_text())['groups']


def domain(value):
    if not isinstance(value, str):
        raise ValueError('A category rule must be a hostname')
    suffix = value.startswith('.')
    host = value[1:] if suffix else value
    try:
        host = host.encode('idna').decode('ascii').lower()
    except UnicodeError:
        raise ValueError('Invalid category hostname') from None
    if (len(host) > 253 or '.' not in host or any(not re.fullmatch(
            r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in host.split('.'))):
        raise ValueError('Invalid category hostname: ' + value)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return ('.' if suffix else '') + host
    raise ValueError('Category rules cannot contain IP addresses')


def selected(names):
    if not isinstance(names, list) or any(not isinstance(x, str) for x in names):
        raise ValueError('Website categories must be a list of names')
    available = catalog()
    if len(set(names)) != len(names) or set(names) - available.keys():
        raise ValueError('Unknown or duplicate website category')
    return list(names)


def fetch(url):
    with urlopen(url, timeout=15) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('Category response is too large')
    return data.decode('utf-8')


def expand_v2fly(name, read, stack=()):
    if name in stack or not re.fullmatch(r'[a-z0-9!-]+', name):
        raise ValueError('Invalid category include: ' + name)
    out = []
    for raw in read(name).splitlines():
        words = raw.split('#', 1)[0].split()
        if not words:
            continue
        token = words[0]
        if token.startswith('include:'):
            if len(words) != 1:
                raise ValueError('Unsupported category include: ' + raw)
            out += expand_v2fly(token[8:], read, stack + (name,))
        elif token.startswith(('regexp:', 'keyword:')):
            raise ValueError('Unsupported category rule: ' + raw)
        else:
            out.append(token[5:] if token.startswith('full:') else '.' + token.removeprefix('domain:'))
    return out


def snapshots(names, saved=None, cache=None, warn=print):
    """Follow trusted sources automatically; use last available data when offline."""
    names = selected(names)
    if not names:
        return {}
    available, saved = catalog(), saved or {}
    cache = Path(cache or Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'pi-sandbox-factory/categories')
    now, result = time.time(), {}

    @lru_cache(maxsize=None)
    def read_v2fly(name):
        return fetch('https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/' + name)

    for name in names:
        path = cache / (name + '.json')
        cached = {}
        try:
            cached = json.loads(path.read_text())
        except (OSError, ValueError):
            pass
        value = copy.deepcopy(cached.get('group') or saved.get(name) or available[name])
        if now - cached.get('checked_at', 0) >= 86400:
            try:
                if name.startswith('dev-'):
                    entries = expand_v2fly(name[4:], read_v2fly)
                else:
                    text = fetch('https://raw.githubusercontent.com/olbat/ut1-blacklists/master/blacklists/' + name[4:] + '/domains')
                    entries = ['.' + line.strip() for line in text.splitlines() if line.strip()]
                domains = set()
                for entry in entries:
                    try:
                        domains.add(domain(entry))
                    except ValueError:
                        continue  # UT1 also contains IP entries; categories grant DNS names only.
                if not domains:
                    raise ValueError('Category contains no usable hostnames')
                value = {**available[name], 'domains': sorted(domains), 'updated_at': now}
                value.pop('revision', None)
            except (OSError, ValueError) as error:
                warn(f"Could not refresh {available[name]['title']}; using the last available list ({error}).")
            else:
                temporary = None
                try:
                    cache.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(mode='w', dir=cache, delete=False) as stream:
                        temporary = Path(stream.name)
                        json.dump({'checked_at': now, 'group': value}, stream)
                    temporary.replace(path)
                except OSError as error:
                    warn(f"Could not cache {available[name]['title']}; using the downloaded list ({error}).")
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        if not isinstance(value.get('domains'), list) or not value['domains']:
            raise ValueError('Empty website category: ' + name)
        value['domains'] = sorted({domain(v) for v in value['domains']})
        result[name] = value
    return result


def collapse(groups):
    values = {domain(v) for group in groups.values() for v in group['domains']}
    suffixes = {v[1:] for v in values if v.startswith('.')}
    result = []
    for value in sorted(values):
        host = value.lstrip('.')
        parts = host.split('.')
        if any('.'.join(parts[i:]) in suffixes for i in range(1, len(parts))):
            continue
        if not value.startswith('.') and host in suffixes:
            continue
        result.append(value)
    return result


def acl(groups):
    domains = collapse(groups)
    if not domains:
        return []
    # Split lines to avoid Squid's maximum configuration line length. Repeated
    # declarations append values to the same ACL.
    declarations = ['acl category_hosts dstdomain -n ' + ' '.join(domains[i:i+40])
                    for i in range(0, len(domains), 40)]
    return declarations + [
        'acl category_private dst ' + PRIVATE_RANGES,
        'acl category_http port 80',
        'acl category_https port 443',
        'acl category_connect method CONNECT',
        'http_access deny category_hosts category_private',
        'http_access allow category_hosts category_https category_connect',
        'http_access allow category_hosts category_http !category_connect',
    ]
