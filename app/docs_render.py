"""Markdown → safe HTML rendering for Team Docs.

This is the security trust boundary for the docs feature. User-authored Markdown
is the source of truth; it is rendered to HTML and then run through nh3 (a Rust
HTML sanitizer) against a strict allowlist before being cached/displayed. The
viewer template renders the cached HTML with `| safe` ONLY because it passed
through here on write — never render raw user content directly.

Pure functions, no Flask imports, so they're trivially unit-testable.
"""
import markdown as _markdown
import nh3

# Hard cap on the Markdown source we will render (defense in depth; the autosave
# route rejects oversize bodies too, and Flask caps the whole request at 5 MB).
MAX_MARKDOWN_BYTES = 200 * 1024

_MD_EXTENSIONS = ['fenced_code', 'tables', 'nl2br', 'sane_lists']

# The only tags we allow out of the renderer.
ALLOWED_TAGS = {
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'hr', 'blockquote',
    'ul', 'ol', 'li',
    'strong', 'em', 'del', 'code', 'pre',
    'a', 'img',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
}

# Per-tag allowed attributes. `rel` on <a> is forced by nh3 (link_rel below), so
# it is deliberately NOT author-controllable here.
ALLOWED_ATTRIBUTES = {
    'a': {'href', 'title'},
    'img': {'src', 'alt', 'title'},
    'th': {'align'},
    'td': {'align'},
}

# Schemes permitted in href/src. No javascript:, no data: — this is what makes
# `[x](javascript:...)` and `![x](data:...)` inert.
ALLOWED_URL_SCHEMES = {'http', 'https', 'mailto'}


def _truncate(md_text: str) -> str:
    encoded = md_text.encode('utf-8')
    if len(encoded) <= MAX_MARKDOWN_BYTES:
        return md_text
    return encoded[:MAX_MARKDOWN_BYTES].decode('utf-8', 'ignore')


def render_markdown(md_text: str) -> str:
    """Render Markdown to sanitized, display-safe HTML."""
    if not md_text:
        return ''
    md_text = _truncate(md_text)
    html = _markdown.markdown(md_text, extensions=_MD_EXTENSIONS, output_format='html5')
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel='noopener noreferrer',
    )


def to_plain_text(md_text: str) -> str:
    """Strip Markdown/HTML down to plain text for search shadowing + previews."""
    if not md_text:
        return ''
    html = _markdown.markdown(_truncate(md_text), extensions=_MD_EXTENSIONS, output_format='html5')
    text = nh3.clean(html, tags=set())  # tags=set() drops every tag, keeps text
    return ' '.join(text.split())[:5000]
