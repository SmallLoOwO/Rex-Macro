# tests/test_web_p5_integration.py
"""P5 Task 8：跨層整合測試 + smoke（spec §5 收尾）.

範圍（brief 列舉的 6 個 scenario）：
1. POST /api/annotate → ``web_history.list_annotations_for_episode`` round-trip
2. snapshot_index.jsonl → GET /api/history 分組正確
3. GET /api/episode/{id} 詳細 + 404；與 ``load_episodes`` 純函式結果一致
4. ``_save_auto_fixture``（Task 5）→ ``list_annotations_for_episode`` round-trip
5. P4 pinch-zoom 座標演算法 lock-in（``client_to_native_coords`` formula reference）
6. 所有 web_* 模組可乾淨 import（smoke）

非目標：本檔不重複 unit test 已覆蓋的單層行為；只測跨層接線。
"""
import importlib
import inspect
import json
import logging
import os
import types

import pytest
from fastapi.testclient import TestClient

from miningbot.web_annotation import build_annotation, validate_annotation
from miningbot.web_history import (
    list_annotations_for_episode,
    load_episodes,
)
from miningbot.web_ipc import FallbackState, PendingReplies
from miningbot.web_protocol import client_to_native_coords
from miningbot.web_server import create_app


# ── helpers ────────────────────────────────────────────────────────────────


def _write_jsonl(path: str, lines: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _make_app(
    *,
    snapshot_index_path: str | None = None,
    fixtures_dir: str | None = None,
) -> TestClient:
    return TestClient(create_app(
        pending=PendingReplies(),
        fallback=FallbackState(),
        broadcast_callback=None,
        snapshot_index_path=snapshot_index_path,
        fixtures_dir=fixtures_dir,
    ))


def _valid_payload() -> dict:
    """通過 validate_annotation 的最小 payload（symptom=false_positive）。"""
    return {
        "image": "auto_007_terrain_fp.png",
        "annotation": {"type": "square", "cx": 211, "cy": 189, "size": 50},
        "tier": None,
        "variant": None,
        "mineral": None,
        "source": {"kind": "manual"},
        "symptom": "false_positive",
        "related_incident": None,
    }


def _zeros(h: int = 270, w: int = 320):
    import numpy as np
    return np.zeros((h, w, 3), dtype=np.uint8)


def _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path):
    """stub bot 僅含 _save_auto_fixture 依賴；_AUTO_FIXTURE_ROOT 改寫到 tmp_path。

    與 ``tests/test_web_intervention.py`` 同模式；P5 Task 8 不能依賴完整 Bot。
    """
    import miningbot.main as main_mod
    from miningbot.main import Bot

    monkeypatch.setattr(main_mod, "_AUTO_FIXTURE_ROOT", str(tmp_path))

    class _StubBot:
        pass

    bot = _StubBot()
    bot.logger = logging.getLogger("test_p5_integration_auto")
    bot.log_discord = logging.getLogger("test_p5_integration_auto")
    bot._save_auto_fixture = types.MethodType(Bot._save_auto_fixture, bot)
    return bot


# ── Scenario 1: POST /api/annotate → list_annotations_for_episode ─────────
# 跨層：HTTP route（web_server）→ atomic write（JSON）→ 讀取（web_history）。
# 揭露設計縫：POST 預設寫到 ``fixtures_dir/aim/`` 子目錄，
# 但 ``list_annotations_for_episode`` 只掃頂層 → parent dir 撈空。
# 子目錄掃描能 round-trip；parent 撈空 lock 為當前行為（待 follow-up 改成遞迴）。


class TestAnnotateRoundTrip:
    def test_annotate_then_list_in_subdir_round_trips_schema(self, tmp_path):
        """POST 寫到 ``aim/`` 子目錄；list 在該子目錄能 round-trip 完整 schema。"""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        client = _make_app(fixtures_dir=str(fixtures))

        r = client.post("/api/annotate", json=_valid_payload())
        assert r.status_code == 201

        written = fixtures / "aim" / "auto_007_terrain_fp.json"
        assert written.exists(), f"POST 未寫入預期路徑：{written}"

        # 子目錄掃描能 round-trip
        result = list_annotations_for_episode("007", str(fixtures / "aim"))
        assert len(result) == 1
        ann = result[0]
        assert ann["image"] == "auto_007_terrain_fp.png"
        assert ann["annotation"] == {
            "type": "square", "cx": 211, "cy": 189, "size": 50,
        }
        assert ann["source"] == {"kind": "manual"}
        assert ann["symptom"] == "false_positive"
        # 來回 validate_annotation 仍通過（list 加的 _source_file 不影響 schema）
        assert validate_annotation(ann) is True

    def test_annotate_subdir_layout_top_level_list_finds_it(self, tmp_path):
        """POST /api/annotate 預設寫到 ``aim/`` 子目錄；
        ``list_annotations_for_episode`` 走 ``os.walk`` 遞迴，從 parent dir 即可撈回。

        P5 final-review Important fix：舊版 ``os.listdir`` 只掃頂層 → parent 撈空，
        玩家可 POST 但 list 回空。此測試 lock 新的遞迴行為。
        """
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        client = _make_app(fixtures_dir=str(fixtures))

        r = client.post("/api/annotate", json=_valid_payload())
        assert r.status_code == 201

        parent_result = list_annotations_for_episode("007", str(fixtures))
        assert len(parent_result) == 1, (
            "list_annotations_for_episode 應遞迴掃描子目錄；parent dir 必須能撈回 "
            "POST /api/annotate 寫入 aim/ 的標註"
        )
        assert parent_result[0]["image"] == "auto_007_terrain_fp.png"


# ── Scenario 2 + 3: snapshot_index.jsonl → history/episode HTTP flow ────────


class TestHistoryFlowIntegration:
    """snapshot_index.jsonl（harvest + reentry）→ HTTP 三條 route 行為正確。"""

    def test_history_groups_harvest_and_reentry_episodes(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png",
             "harvest_id": "007"},
            {"written_at": 1001.0, "label": "007_b", "path": "/b.png",
             "harvest_id": "007"},
            {"written_at": 3000.0, "label": "reentry_ep5_dir1", "path": "/c.png",
             "harvest_id": None},
        ])
        client = _make_app(snapshot_index_path=str(idx))

        r = client.get("/api/history")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        by_id = {e["harvest_id"]: e for e in data}
        assert by_id["007"]["type"] == "harvest"
        assert by_id["007"]["count"] == 2
        assert by_id["5"]["type"] == "reentry"

    def test_episode_detail_returns_snapshots_and_404_on_missing(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png",
             "harvest_id": "007"},
        ])
        client = _make_app(snapshot_index_path=str(idx))

        r_ok = client.get("/api/episode/007")
        assert r_ok.status_code == 200
        detail = r_ok.json()
        assert detail["harvest_id"] == "007"
        assert len(detail["snapshots"]) == 1
        assert detail["snapshots"][0]["label"] == "007_a"

        r_miss = client.get("/api/episode/999")
        assert r_miss.status_code == 404

    def test_http_history_agrees_with_load_episodes_pure_fn(self, tmp_path):
        """HTTP 結果應與直接呼叫 ``load_episodes`` 一致（cross-layer sanity）。"""
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png",
             "harvest_id": "007"},
            {"written_at": 2000.0, "label": "009_a", "path": "/b.png",
             "harvest_id": "009"},
        ])
        client = _make_app(snapshot_index_path=str(idx))

        http_ids = sorted(e["harvest_id"]
                         for e in client.get("/api/history").json())
        pure_ids = sorted(e["harvest_id"]
                         for e in load_episodes(str(idx)))
        assert http_ids == pure_ids == ["007", "009"]


# ── Scenario 4: 自動收集素材 → list_annotations_for_episode 整合 ──────────


class TestAutoFixtureIntegration:
    """``_save_auto_fixture`` 寫入的 .json 應能被 ``list_annotations_for_episode``
    在對應子目錄撈到並通過 ``validate_annotation``。

    cross-task 驗收：Task 5 寫入路徑 ↔ Task 4 schema 兩側自洽。
    """

    def test_harvest_success_fixture_round_trips_in_aim_subdir(
        self, monkeypatch, tmp_path,
    ):
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        bot._save_auto_fixture(
            flow="harvest", episode_id="007", frame=_zeros(1080, 1920),
            cell_crop=_zeros(270, 320), annotation_xy=(160, 135),
            verify_ok=True,
        )

        aim_dir = tmp_path / "aim"
        result = list_annotations_for_episode("007", str(aim_dir))
        assert len(result) == 1
        ann = result[0]
        assert validate_annotation(ann) is True
        assert ann["source"]["kind"] == "auto"
        assert ann["symptom"] is None  # verify 通過 = 對照組

    def test_harvest_fail_fixture_round_trips_with_unknown_symptom(
        self, monkeypatch, tmp_path,
    ):
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        bot._save_auto_fixture(
            flow="harvest", episode_id="042", frame=_zeros(1080, 1920),
            cell_crop=_zeros(270, 320), annotation_xy=(100, 100),
            verify_ok=False,
        )

        result = list_annotations_for_episode("042", str(tmp_path / "aim"))
        assert len(result) == 1
        ann = result[0]
        assert validate_annotation(ann) is True
        assert ann["symptom"] == "unknown"  # verify 失敗 → 標 unknown
        assert ann["source"]["episode_result"] == "fail"

    def test_reentry_fixture_round_trips_in_teleport_board_subdir(
        self, monkeypatch, tmp_path,
    ):
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        bot._save_auto_fixture(
            flow="reentry", episode_id="5", frame=_zeros(1080, 1920),
            cell_crop=None, annotation_xy=(960, 540), verify_ok=True,
        )

        sub = tmp_path / "reentry" / "teleport_board"
        result = list_annotations_for_episode("5", str(sub))
        assert len(result) == 1
        assert validate_annotation(result[0]) is True


# ── Scenario 5: P4 pinch-zoom 演算法 lock-in（client_to_native_coords） ────


class TestPinchZoomAlgorithmLockIn:
    """P4 Critical pinch-zoom 座標協議（P5 Task 1 修復）：JS 端自己換算原生座標；
    server 端 ``client_to_native_coords`` 是 formula reference，必須維持 stable
    signature 與數學行為。本 class lock 演算法，避免後續 refactor 破壞協議。
    """

    def test_function_exports_with_documented_signature(self):
        """5 個參數 + 預設值（pan_offset=(0,0)、zoom=1.0）必須穩定。"""
        sig = inspect.signature(client_to_native_coords)
        params = list(sig.parameters.keys())
        assert params == [
            "client_xy", "canvas_size", "native_size",
            "pan_offset", "zoom",
        ], f"signature unstable: {params}"
        assert sig.parameters["pan_offset"].default == (0.0, 0.0)
        assert sig.parameters["zoom"].default == 1.0

    def test_formula_unzoom_then_scale_then_pan_then_clamp(self):
        """演算法順序：除 zoom → scale canvas→native → 加 pan → clamp。

        canvas 顯示 960×540、zoom=2x、pan_offset=(10, 10)，點 canvas (200, 100)
        step1: (200, 100) / 2 = (100, 50)
        step2: * (1920/960, 1080/540) = (200, 100)
        step3: + (10, 10) = (210, 110)
        """
        result = client_to_native_coords(
            client_xy=(200, 100),
            canvas_size=(960, 540),
            native_size=(1920, 1080),
            pan_offset=(10, 10),
            zoom=2.0,
        )
        assert result == (210, 110)

    def test_clamp_to_native_bounds(self):
        """clamp 確保玩家平移出界送了負值或超界不會炸下游。"""
        assert client_to_native_coords(
            client_xy=(-100, -100),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
        ) == (0, 0)
        assert client_to_native_coords(
            client_xy=(10000, 10000),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
        ) == (1919, 1079)


# ── Scenario 6: cross-task import sanity（所有 web_* 模組） ────────────────


_WEB_MODULES = [
    "miningbot.web_protocol",
    "miningbot.web_ipc",
    "miningbot.web_sink",
    "miningbot.web_config_whitelist",
    "miningbot.web_config_persistence",
    "miningbot.web_static",
    "miningbot.web_annotation",
    "miningbot.web_history",
    "miningbot.web_server",
]


class TestWebModulesImportCleanly:
    """所有 web_* 模組可乾淨 import；P1-P5 任何 refactor 導致 ImportError 會被此
    class 抓到（smoke）。
    """

    @pytest.mark.parametrize("module_name", _WEB_MODULES)
    def test_module_imports(self, module_name):
        mod = importlib.import_module(module_name)
        assert mod is not None
        assert mod.__name__ == module_name


# ── Scenario 7: build_annotation → validate → POST round-trip ──────────────


def test_build_annotation_round_trips_through_validate_and_post(tmp_path):
    """``build_annotation`` 輸出必須同時通過 ``validate_annotation`` 與 POST。

    證明純函式（web_annotation）↔ HTTP route（web_server）schema 一致；
    normalize_symptom（"漏判" → "false_negative"）也在此驗收。
    """
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    client = _make_app(fixtures_dir=str(fixtures))

    ann = build_annotation(
        image="manual_007_test.png",
        annotation={"type": "square", "cx": 100, "cy": 100, "size": 30},
        tier="Mythic",
        variant="Spectral",
        mineral="Tin",
        source={"kind": "manual"},
        symptom="漏判",  # 玩家可見中文 → normalize_symptom → "false_negative"
        related_incident=None,
    )

    # 純函式 schema 自洽
    assert validate_annotation(ann) is True
    assert ann["symptom"] == "false_negative"

    # HTTP endpoint 也接受
    r = client.post("/api/annotate", json=ann)
    assert r.status_code == 201, f"POST 拒絕了 build_annotation 輸出：{r.json()}"
    written = fixtures / "aim" / "manual_007_test.json"
    assert written.exists()
    # round-trip 內容一致（atomic write 不丟欄位）
    reloaded = json.loads(written.read_text(encoding="utf-8"))
    assert reloaded == ann


def test_full_flow_index_history_episode_annotate_chain(tmp_path):
    """組合：snapshot_index → history → episode → annotate 一條龍。

    模擬玩家從歷史列表點進 episode 007 → 看到詳細 → 開標註工具送素材 →
    素材出現在該 episode 的子目錄裡。
    """
    idx = tmp_path / "snapshot_index.jsonl"
    _write_jsonl(str(idx), [
        {"written_at": 1000.0, "label": "007_a", "path": "/a.png",
         "harvest_id": "007"},
        {"written_at": 1001.0, "label": "007_b", "path": "/b.png",
         "harvest_id": "007"},
    ])
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    client = _make_app(
        snapshot_index_path=str(idx),
        fixtures_dir=str(fixtures),
    )

    # Step 1: history 列表
    history = client.get("/api/history").json()
    assert any(e["harvest_id"] == "007" for e in history)

    # Step 2: episode 詳細
    detail = client.get("/api/episode/007").json()
    assert detail["harvest_id"] == "007"
    assert len(detail["snapshots"]) == 2

    # Step 3: 玩家送標註（以 manual_007_<ts>.png 命名）
    payload = _valid_payload()
    payload["image"] = "manual_007_player1.png"
    r = client.post("/api/annotate", json=payload)
    assert r.status_code == 201

    # Step 4: 標註出現在該 episode 的 aim/ 子目錄裡（list 在子目錄能找到）
    anns = list_annotations_for_episode("007", str(fixtures / "aim"))
    manual_anns = [a for a in anns if a["image"].startswith("manual_007_")]
    assert len(manual_anns) == 1
    assert manual_anns[0]["image"] == "manual_007_player1.png"
