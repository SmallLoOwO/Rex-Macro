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

    自動收集的 `auto_*`（玩家網頁介入的副產品）例外——那是 runtime 產物、數量無上限，
    命名規則寫在 README 就夠，不必逐檔列。
    """
    readme = (subdir / "README.md").read_text(encoding="utf-8")
    missing = []
    for asset in sorted(subdir.iterdir()):
        if asset.is_dir() or asset.suffix.lower() not in _ASSET_SUFFIXES:
            continue
        if asset.name.startswith("auto_"):
            continue
        if asset.name not in readme and asset.stem not in readme:
            missing.append(asset.name)
    assert missing == [], (
        f"{subdir.name}/README.md 沒提到這些素材：{missing}。"
        "加素材時要同步更新該目錄的表格，否則索引就過期了。")
