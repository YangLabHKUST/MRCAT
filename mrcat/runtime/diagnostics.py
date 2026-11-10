"""Bounded failure diagnostics without credentials or authorization headers."""
import os
import re
import traceback


def redact(text):
    text = str(text)
    for name, value in os.environ.items():
        if len(value) >= 6 and any(word in name.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            text = text.replace(value, '[REDACTED]')
    text = re.sub(r'(?i)(bearer\s+)[^\s\"\',}]+', r'\1[REDACTED]', text)
    text = re.sub(r'''(?ix)(["']?(?:api[_-]?key|access[_-]?token|authorization|password|secret)["']?\s*[:=]\s*["']?)[^\s"',}]+''', r'\1[REDACTED]', text)
    # Signed links may contain credentials even when not present in the environment.
    text = re.sub(r'(https?://[^\s?"\']+)\?[^\s"\']+', r'\1?[REDACTED]', text)
    return text


def exception_details(exc):
    return dict(type=type(exc).__name__, message=redact(str(exc))[:12000],
                traceback=redact(''.join(traceback.format_exception(exc)))[-18000:])


def redact_data(value):
    """Redact response strings without losing the JSON response structure."""
    if isinstance(value, dict):
        return {key: ('[REDACTED]' if re.fullmatch(
            r'(?i)(api[_-]?key|access[_-]?token|authorization|password|secret)', str(key))
            else redact_data(item)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_data(item) for item in value]
    return redact(value) if isinstance(value, str) else value
