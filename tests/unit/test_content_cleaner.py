from __future__ import annotations

from competitive_intel.domain.content_cleaner import clean_page
from competitive_intel.domain.webpage import CleanPageRequest, CleanStatus


def _clean(html: str):
    return clean_page(
        CleanPageRequest(
            raw_html=html,
            url="https://example.com/pricing",
            cleaner_version="test-v1",
        )
    )


def test_removes_template_noise_and_preserves_product_content(fixture_pages) -> None:
    result = _clean(fixture_pages["static"])

    assert result.clean_status == CleanStatus.SUCCESS
    assert result.page_title == "Acme Workspace"
    assert "Global announcement" not in result.clean_content
    assert "Home Pricing Login" not in result.clean_content
    assert "Copyright and legal links" not in result.clean_content
    assert "window.analytics" not in result.clean_content
    assert "Acme Workspace" in result.clean_content
    assert "Docs and tasks" in result.clean_content
    assert "Plan" in result.clean_content
    assert "$12 per user / month" in result.clean_content
    assert result.clean_content.count("Plan projects with your team.") == 1


def test_same_html_produces_identical_content_and_hash(fixture_pages) -> None:
    first = _clean(fixture_pages["static"])
    second = _clean(fixture_pages["static"])

    assert first.clean_content == second.clean_content
    assert first.clean_hash == second.clean_hash
    assert first.content_length == len(first.clean_content)


def test_content_change_produces_a_different_hash(fixture_pages) -> None:
    original = _clean(fixture_pages["static"])
    changed = _clean(fixture_pages["changed"])

    assert original.clean_hash != changed.clean_hash
    assert "$15 per user / month" in changed.clean_content


def test_article_is_used_before_body() -> None:
    html = """
    <html><head><title>Article page</title></head><body>
      <p>Body-only noise</p>
      <article><h1>Release notes</h1><p>Added workflow automation.</p></article>
    </body></html>
    """

    result = _clean(html)

    assert result.clean_content == "Release notes\nAdded workflow automation."
    assert "Body-only noise" not in result.clean_content


def test_prices_nested_inline_text_and_conditions_remain_contiguous():
    result = _clean('<main><h2>Pro</h2><div><span>$</span><span>10</span> USD</div>'
                    '<label>per user/month</label><div>Billed yearly</div>'
                    '<p>Other conditions apply.</p><h2>Business</h2><div>$20 USD</div></main>')
    assert result.clean_content == 'Pro\n$ 10 USD\nper user/month\nBilled yearly\nOther conditions apply.\nBusiness\n$20 USD'
    assert result.clean_content.count('$ 10') == 1
    assert 'Billed yearly\nBusiness' not in result.clean_content


def test_hidden_noise_removed_but_repeated_table_cells_kept():
    html = ('<style>.secret {display:none}</style><main><div hidden>Hidden</div>'
            '<span aria-hidden="true">Duplicate</span><div style="visibility:hidden">Invisible</div>'
            '<div class="secret">CSS hidden</div><script>secret()</script>'
            '<table><tr><td>Unlimited</td><td>Unlimited</td></tr></table></main>')
    result = _clean(html)
    assert result.clean_content == 'Unlimited\nUnlimited'


def test_conditional_css_is_not_applied_without_a_viewport():
    html = '<style>@media(max-width:500px){.price{display:none}}</style><main><div class="price">$10 USD</div></main>'
    assert '$10 USD' in _clean(html).clean_content
