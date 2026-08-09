"""Current-documentation contracts.

Historical plans and incident records are intentionally excluded: they preserve
point-in-time evidence.  These checks cover only files presented as current
operator/developer guidance.
"""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
CURRENT_GUIDANCE = (
    "AGENTS.md",
    "README.md",
    "assets/README.md",
    "docs/game-mechanics.md",
    "docs/manual-sampling.md",
    "miningbot/AGENTS.md",
    "tests/AGENTS.md",
)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


STALE_CLAIMS = {
    "legacy nine-world wording": re.compile(
        r"\bnine-world\b|\b9-world\b|全部世界\*\*（9 個）",
        re.IGNORECASE,
    ),
    "two-world implementation wording": re.compile(
        r"目前有 \*\*Aesteria \+ Lucernia\*\*|目前實作 \*\*Aesteria\*\*"
    ),
    "legacy auto_reenter setting": re.compile(
        r"`auto_reenter`|(?<!_)auto_reenter (?:開|未啟用|預設)"
    ),
    "tracker-disappearance success shortcut": re.compile(
        r"tracker 立即消失\s*=\s*成功|tracker 框\*\*立即消失\*\*"
    ),
    "obsolete two-world rare count": re.compile(r"254 個"),
}


@pytest.mark.parametrize("relative_path", CURRENT_GUIDANCE)
@pytest.mark.parametrize("label, pattern", STALE_CLAIMS.items())
def test_current_guidance_has_no_stale_claim(relative_path, label, pattern):
    assert pattern.search(_read(relative_path)) is None, (
        f"{relative_path} still contains {label}"
    )


@pytest.mark.parametrize("relative_path", ("AGENTS.md", "tests/AGENTS.md"))
def test_guidance_does_not_embed_volatile_test_totals(relative_path):
    text = _read(relative_path)
    assert re.search(r"\*\*\d+\s+(?:tests\s+)?(?:collected|passed)", text) is None

