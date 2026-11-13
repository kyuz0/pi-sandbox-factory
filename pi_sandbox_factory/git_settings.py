"""Optional sandbox-wide commit identity; SSH authentication is independent."""
import json
import re


def identity(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'name', 'email'}:
        raise ValueError('Git commit identity needs a name and email')
    name, email = value['name'], value['email']
    if isinstance(name, str) and not name.strip(' ,;:\"\'\\@\t'):
        raise ValueError('Enter a Git commit author name')
    if not isinstance(name, str) or not name.strip() or len(name) > 200 or any(ord(c) < 32 or c in '<>\x7f' for c in name):
        raise ValueError('Enter a Git commit name without line breaks or angle brackets')
    if (not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+', email)
            or any(ord(c) < 32 or ord(c) == 127 for c in email)):
        raise ValueError('Enter a Git commit email such as developer@example.com')
    return {'name': name.strip(), 'email': email}


def config(value):
    value = identity(value)
    if value is None:
        return '# No Factory Git commit identity selected.\n'
    return '[user]\n' + ''.join('\t' + key + ' = ' + json.dumps(value[key], ensure_ascii=False) + '\n'
                               for key in ('name', 'email'))
