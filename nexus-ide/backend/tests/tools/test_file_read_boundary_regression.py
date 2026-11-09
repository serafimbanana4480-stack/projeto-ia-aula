"""Regression for the real discount benchmark's copied protection text."""
import ast

import pytest

from backend.tools.registry import frame_external_result
from backend.tools.sanitizer import PREAMBLE


def test_recorded_corrupt_result_is_invalid_python():
    # Exact final content from run-4efab3d83d1f419386c0e5732acc44e0.
    text = (PREAMBLE + "\n---\ndef total(price, percent):\n"
            "    return price - price * percent / 100\n\n---\n")
    assert PREAMBLE in text
    with pytest.raises(SyntaxError):
        ast.parse(text)


@pytest.mark.parametrize("tool", ["read_file", "read_file_absolute"])
def test_file_read_keeps_warning_outside_content(tool):
    original = "def total(price, percent):\n    return price + price * percent / 100\n"
    result = frame_external_result(tool, {"path": "app/pricing.py", "content": original})
    assert PREAMBLE not in result["content"]
    assert PREAMBLE in result["content_warning"]
    assert 'trust_level="untrusted"' in result["content"]
    assert original in result["content"]
    assert "\n---\n" not in result["content"]
    assert frame_external_result(tool, result)["content"] == result["content"]
