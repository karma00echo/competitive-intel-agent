"""Offline checks for isolated, equal-function visual explorations."""
from pathlib import Path
import re

from bs4 import BeautifulSoup
import pytest


ROOT = Path(__file__).resolve().parents[2] / "ui-demos"
DESIGNS = ["01-studio", "02-nightfall", "03-editorial", "04-precision"]


@pytest.mark.parametrize("design", DESIGNS)
def test_demos_share_data_and_behavior_with_local_assets(design):
    entry = ROOT / design / "index.html"
    soup = BeautifulSoup(entry.read_text(encoding="utf-8"), "html.parser")
    assert [s["src"] for s in soup.find_all("script")] == [
        "../shared/data.js", "../shared/app.js"
    ]
    assert [s["href"] for s in soup.find_all("link")] == [
        "../shared/base.css", "theme.css"
    ]
    for asset in soup.find_all(["script", "link"]):
        path = (entry.parent / (asset.get("src") or asset["href"])).resolve()
        assert path.is_relative_to(ROOT.resolve()) and path.is_file()


def test_demo_has_no_backend_or_network_access():
    script = (ROOT / "shared/app.js").read_text(encoding="utf-8")
    assert not re.search(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(", script)
    assert "/api/" not in script
    assert "innerHTML" not in script
    assert "textContent" in script
    for name in ["Command Center", "Signals", "Analyst", "Competitors", "Reports", "Developer"]:
        assert name in script
    assert "No verified facts available yet." in script
    assert "Natural-language Analyst is not connected yet." in script


def test_visual_directions_are_distinct_but_do_not_hide_functionality():
    styles = [(ROOT / design / "theme.css").read_text(encoding="utf-8") for design in DESIGNS]
    assert len(set(styles)) == 4
    assert all("display:none" not in style and "visibility:hidden" not in style for style in styles)
    assert all("url(" not in style and "@import" not in style for style in styles)
