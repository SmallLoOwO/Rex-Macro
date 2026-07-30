"""素材庫索引守門（spec §5「每個子目錄有 README.md，AI agent 友善索引」）。

素材是給**看不到圖**的人／agent 用的：沒有 README 就只剩檔名，判定門檻、兩側夾、
負樣本在哪全都要重新從測試碼反推。這幾個測試確保索引不會隨著新增素材而腐化。
"""
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
INDEX = FIXTURES / "README.md"

# 素材副檔名（README.md 本身不算素材）
_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".wav", ".json"}

# runtime 快照 stem：`diagnostics` 的 `%Y%m%d_%H%M%S_<ns>_…`。`/api/annotate` 用它
# 當玩家手動標註素材的檔名，所以這些檔跟 `auto_*` 一樣不必逐檔列進 README。
_RUNTIME_STEM = re.compile(r"^\d{8}_\d{6}_\d+_")


def _fixture_dirs():
    return sorted(p for p in FIXTURES.iterdir() if p.is_dir())


def test_top_level_index_exists():
    assert INDEX.exists(), (
        "tests/fixtures/README.md 是素材庫頂層索引（spec §5），不得缺席")


@pytest.mark.parametrize("subdir", _fixture_dirs(), ids=lambda p: p.name)
def test_every_fixture_dir_has_readme(subdir):
    assert (subdir / "README.md").exists(), (
        f"{subdir.name}/ 缺 README.md——說明該類別的判定、命名與兩側夾。"
        "看不到圖的人只靠檔名無法判斷素材該不該動。")


@pytest.mark.parametrize("subdir", _fixture_dirs(), ids=lambda p: p.name)
def test_every_fixture_dir_is_listed_in_index(subdir):
    """新增目錄必須同步進頂層索引，否則等於沒加。"""
    text = INDEX.read_text(encoding="utf-8")
    assert f"{subdir.name}/" in text, (
        f"tests/fixtures/README.md 的目錄一覽沒有 {subdir.name}/")


def test_index_links_all_resolve():
    """索引裡的相對連結不得斷鏈。"""
    text = INDEX.read_text(encoding="utf-8")
    broken = [target for target in re.findall(r"\]\(([^)]+)\)", text)
              if not target.startswith(("http://", "https://"))
              and not (INDEX.parent / target).exists()]
    assert broken == [], f"頂層索引有斷鏈：{broken}"


@pytest.mark.parametrize("subdir", _fixture_dirs(), ids=lambda p: p.name)
def test_readme_mentions_every_asset(subdir):
    """每個素材檔都要在該目錄 README 裡被提到（檔名或去掉副檔名的名字）。

    Runtime 產物例外（數量無上限，命名規則寫在 README 就夠，不必逐檔列）：

    - `auto_*`：`main.Bot._save_auto_fixture` 在玩家網頁介入後寫的。
    - 快照 stem 命名（`_RUNTIME_STEM`）：`POST /api/annotate` 用**原始快照檔名**
      寫玩家手動標註的 crop+json（`web_server.post_api_annotate`，檔名來自
      `diagnostics` 的 `%Y%m%d_%H%M%S_<ns>_…`）。這條路徑跟 `auto_*` 同樣是
      runtime 寫入、同樣落進 `tests/fixtures/<category>/`，卻沒有 `auto_` 前綴——
      2026-07-30 前這裡沒放行它，於是**玩家每標註一張，測試就紅一次**，除非有人
      手動把檔名補進 README 表格。那是索引守門的假警報，不是素材漏登記。
    """
    readme = (subdir / "README.md").read_text(encoding="utf-8")
    missing = []
    for asset in sorted(subdir.iterdir()):
        if asset.is_dir() or asset.suffix.lower() not in _ASSET_SUFFIXES:
            continue
        if asset.name.startswith("auto_") or _RUNTIME_STEM.match(asset.name):
            continue
        if asset.name not in readme and asset.stem not in readme:
            missing.append(asset.name)
    assert missing == [], (
        f"{subdir.name}/README.md 沒提到這些素材：{missing}。"
        "加素材時要同步更新該目錄的表格，否則索引就過期了。")
