"""Sanitized Markdown using the existing session artifact routes."""
import re
import bleach
import markdown


def render_markdown(text, artifact_url):
    text = re.sub(r'(\]\()(?:\./)?((?:workspace|executions)/[^)]+)\)',
                  lambda m: '](' + artifact_url(m.group(2)) + ')', text)
    return bleach.clean(markdown.markdown(text, extensions=['tables', 'fenced_code']),
        tags=set(bleach.sanitizer.ALLOWED_TAGS) | {'p', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'img', 'br'},
        attributes={'a': ['href', 'title'], 'img': ['src', 'alt']})
