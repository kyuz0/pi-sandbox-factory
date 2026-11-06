"""Communication integrations and their network requirements."""


def settings(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {'slack'}:
        raise ValueError('Unknown communication channel')
    result = {'slack': False, **value}
    if type(result['slack']) is not bool:
        raise ValueError('Slack must be enabled or disabled')
    return result


def destinations(value):
    return [('slack.com', 443), ('files.slack.com', 443)] if settings(value)['slack'] else []
