"""Wave 0 — docs_render, the wiki-HTML sanitization trust boundary.

This module renders the one `| safe` field in the application (the docs
viewer), so its allowlist is load-bearing security code. It is Flask-free by
design, so it needs no app context.
"""
import pytest

from app.docs_render import render_markdown, to_plain_text


@pytest.mark.unit
@pytest.mark.security
class TestSanitization:
    def test_script_tag_stripped(self):
        out = render_markdown('hello <script>alert(1)</script> world')
        assert '<script' not in out.lower()
        assert 'alert(1)' not in out or '<script' not in out.lower()

    def test_javascript_scheme_removed(self):
        out = render_markdown('[click](javascript:alert(1))')
        assert 'javascript:' not in out.lower()

    def test_onerror_attribute_stripped(self):
        out = render_markdown('<img src=x onerror="alert(1)">')
        assert 'onerror' not in out.lower()

    def test_onclick_attribute_stripped(self):
        out = render_markdown('<div onclick="steal()">x</div>')
        assert 'onclick' not in out.lower()

    def test_iframe_stripped(self):
        out = render_markdown('<iframe src="https://evil.example"></iframe>')
        assert '<iframe' not in out.lower()

    def test_data_uri_image_rejected(self):
        out = render_markdown('![x](data:text/html,<script>alert(1)</script>)')
        assert 'data:text/html' not in out.lower()

    def test_style_attribute_not_arbitrary(self):
        # style with an expression / url() should not survive as an attack vector
        out = render_markdown('<p style="background:url(javascript:alert(1))">x</p>')
        assert 'javascript:' not in out.lower()


@pytest.mark.unit
class TestLegitimateMarkdown:
    def test_heading_rendered(self):
        assert '<h1' in render_markdown('# Title').lower()

    def test_bold_rendered(self):
        assert '<strong>' in render_markdown('**bold**').lower()

    def test_safe_link_preserved(self):
        out = render_markdown('[docs](https://example.com/page)')
        assert 'https://example.com/page' in out

    def test_relative_link_preserved(self):
        out = render_markdown('[file](/static/a.pdf)')
        assert '/static/a.pdf' in out

    def test_ampersand_not_double_escaped(self):
        out = render_markdown('a & b')
        assert '&amp;amp;' not in out

    def test_code_block_rendered(self):
        out = render_markdown('```\nprint(1)\n```')
        assert '<code' in out.lower() or '<pre' in out.lower()


@pytest.mark.unit
class TestPlainText:
    def test_strips_markdown_formatting(self):
        assert to_plain_text('# Head\n\nBody **bold**') == 'Head Body bold'

    def test_empty_input(self):
        assert to_plain_text('') == ''

    def test_strips_html(self):
        result = to_plain_text('<p>hello <b>world</b></p>')
        assert '<' not in result
        assert 'hello' in result and 'world' in result


@pytest.mark.unit
class TestSizeCap:
    def test_oversized_input_is_capped(self):
        # docs_render caps input at 200 KB (MAX_MARKDOWN_BYTES). Feed just over
        # the cap and confirm the rendered output reflects truncated input, not
        # the full payload.
        from app.docs_render import MAX_MARKDOWN_BYTES
        over = 'x' * (MAX_MARKDOWN_BYTES + 50_000)  # ~250 KB, one paragraph
        out = render_markdown(over)
        assert isinstance(out, str)
        # truncated to the cap, so fewer than the full 250 KB of x's survive
        assert out.count('x') <= MAX_MARKDOWN_BYTES
