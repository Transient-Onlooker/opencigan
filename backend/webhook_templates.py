"""Render explicitly configured webhook templates without performing delivery."""

import re
from string import Formatter

MAX_TEMPLATE_LENGTH = 1200
MAX_OUTPUT_LENGTH = 1800
ALLOWED_FIELDS = frozenset({'school', 'grade', 'classroom', 'date', 'period', 'type', 'before', 'after'})
_URL = re.compile(
    r'(?i)(?:\b(?:https?|ftp|file|javascript|data|mailto|tel|sms)\s*:\s*(?://)?'
    r'|\b[a-z][a-z0-9+.-]{0,31}\s*:\s*//'
    r'|(?<![\w@])www\s*\.\s*'
    r'|(?<![\w])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+'
    r'(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})(?![\w-]))'
)
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def render_template(provider, template, values, *, discord_embed=False):
    if provider not in ('discord', 'google-chat') or not isinstance(template, str) or not template.strip():
        raise ValueError('invalid template')
    if len(template) > MAX_TEMPLATE_LENGTH or not isinstance(values, dict):
        raise ValueError('invalid template')
    if type(discord_embed) is not bool or (discord_embed and provider != 'discord'):
        raise ValueError('invalid format')

    fields = set()
    try:
        for _, name, format_spec, conversion in Formatter().parse(template):
            if name is None:
                continue
            if name not in ALLOWED_FIELDS or format_spec or conversion:
                raise ValueError('unsupported placeholder')
            fields.add(name)
        if any(name not in values or not isinstance(values[name], (str, int)) or isinstance(values[name], bool) for name in fields):
            raise ValueError('missing placeholder value')
        text = template.format_map({name: str(values[name]) for name in fields})
    except (KeyError, IndexError, AttributeError, ValueError):
        raise ValueError('invalid template or placeholder') from None

    text = _CONTROL.sub('', text).replace('<', '＜').replace('>', '＞')
    text = _URL.sub(lambda match: match.group(0).replace(':', '：').replace('.', '．').replace('/', '／'), text)
    if len(text) > MAX_OUTPUT_LENGTH:
        raise ValueError('rendered message too long')
    if provider == 'discord':
        if discord_embed:
            return {'embeds': [{'description': text}], 'allowed_mentions': {'parse': []}}
        return {'content': text, 'allowed_mentions': {'parse': []}}
    return {'text': text}
