"""手動標註必須產出 .png + .json 兩檔一組（spec §5）。

先前 `POST /api/annotate` 只寫 json，`image` 欄放的是**原始快照**的 basename，
而那個檔名在 `tests/fixtures/` 底下根本不存在——實測 `aim/` 有 3 個 png、0 個 json，
兩邊從來對不起來。素材的用途就是拿去加強目標框偵測，沒有裁圖等於什麼都沒收到。

PNG 必須是**檢測函式吃的格式**（320×270 粗格裁圖），跟自動收集路徑
（`main._save_auto_fixture`）產出的形狀一致，兩者共用 `cell_crop_box`。
"""
import json
import os

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from miningbot.web_annotation import cell_crop_box
from miningbot.web_ipc import PendingReplies, FallbackState
from miningbot.web_server import create_app


# ── 純函式：裁切幾何 ───────────────────────────────────────────────────────

def test_cell_crop_box_is_320x270_on_1080p():
    """既有 aim/ fixture 與 detect_tracker_core 的輸入尺寸。"""
    x0, y0, x1, y1 = cell_crop_box(1920, 1080, 960, 540)
    assert (x1 - x0, y1 - y0) == (320, 270)


def test_cell_crop_box_centres_on_point():
    x0, y0, x1, y1 = cell_crop_box(1920, 1080, 960, 540)
    assert (x0 + x1) // 2 == 960
    assert (y0 + y1) // 2 == 540


def test_cell_crop_box_clamps_at_origin():
    """左上角附近不得產生負座標（numpy 負索引會裁到對面去）。"""
    x0, y0, x1, y1 = cell_crop_box(1920, 1080, 10, 10)
    assert x0 == 0 and y0 == 0
    assert x1 > 0 and y1 > 0


def test_cell_crop_box_matches_legacy_main_geometry():
    """與 main.py 舊版逐字寫法對齊——兩條路徑必須產出同形狀素材。

    舊寫法貼右／下緣時裁圖會**比一格窄**（起點不往回推），這裡刻意保留該行為。
    """
    W, H = 1920, 1080
    cw, ch = W // 6, H // 4
    for cx, cy in [(0, 0), (960, 540), (1919, 1079), (1900, 100), (50, 1050)]:
        legacy_x0 = max(0, cx - cw // 2)
        legacy_y0 = max(0, cy - ch // 2)
        legacy = (legacy_x0, legacy_y0,
                  min(W, legacy_x0 + cw), min(H, legacy_y0 + ch))
        assert cell_crop_box(W, H, cx, cy) == legacy


# ── route：兩檔一組 ───────────────────────────────────────────────────────

@pytest.fixture
def parts(tmp_path):
    """snapshots_root 底下放一張可辨識的假全幀。"""
    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    fixtures = tmp_path / "fixtures"
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[:, :] = (10, 20, 30)
    # 在 (960, 540) 畫一塊亮色，用來確認裁圖真的取到中心那一帶
    cv2.rectangle(frame, (940, 520), (980, 560), (0, 255, 0), -1)
    src = snaps / "20260726_000001_000000000_000001_113_sweep_aim.png"
    ok, enc = cv2.imencode(".png", frame)
    assert ok
    enc.tofile(str(src))

    app = create_app(
        PendingReplies(), FallbackState(), broadcast_callback=None,
        fixtures_dir=str(fixtures), snapshots_root=str(snaps),
    )
    return TestClient(app), str(src), fixtures


def _payload(src, cx=960, cy=540, size=50, **extra):
    body = {
        "image": os.path.basename(src),
        "source_path": src,
        "annotation": {"type": "square", "cx": cx, "cy": cy, "size": size},
        "tier": "Exotic", "variant": None, "mineral": None,
        "source": {"kind": "manual"},
        "symptom": "false_negative", "related_incident": None,
    }
    body.update(extra)
    return body


def test_annotate_writes_png_and_json_pair(parts):
    client, src, fixtures = parts
    r = client.post("/api/annotate", json=_payload(src))
    assert r.status_code == 201
    stem = os.path.splitext(os.path.basename(src))[0]
    png = fixtures / "aim" / (stem + ".png")
    js = fixtures / "aim" / (stem + ".json")
    assert png.is_file(), "沒有配對的裁圖＝素材無法拿去加強偵測"
    assert js.is_file()
    assert r.json()["png"] == str(png)


def test_written_png_is_detector_input_size(parts):
    """裁圖必須是 320×270——detect_tracker_core 與既有 aim/ fixture 的格式。"""
    client, src, fixtures = parts
    client.post("/api/annotate", json=_payload(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    png = fixtures / "aim" / (stem + ".png")
    img = cv2.imdecode(np.fromfile(str(png), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (270, 320)


def test_written_png_contains_the_annotated_region(parts):
    """裁圖真的取到玩家框的那一帶（不是隨便一塊畫面）。"""
    client, src, fixtures = parts
    client.post("/api/annotate", json=_payload(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    png = fixtures / "aim" / (stem + ".png")
    img = cv2.imdecode(np.fromfile(str(png), dtype=np.uint8), cv2.IMREAD_COLOR)
    # 全幀在 (960,540) 附近畫了純綠塊；裁圖中心必須是那個綠
    assert tuple(int(v) for v in img[135, 160]) == (0, 255, 0)


def test_json_coords_are_crop_local(parts):
    """json 描述的是它旁邊那張 png，座標必須換算成裁圖內座標。

    與自動收集路徑的 `annotation_xy`（main.py 傳 `x - cx0, y - cy0`）語意一致，
    也對得上 spec 範例（cx=211, cy=189 落在 320×270 內）。
    """
    client, src, fixtures = parts
    client.post("/api/annotate", json=_payload(src, cx=960, cy=540))
    stem = os.path.splitext(os.path.basename(src))[0]
    data = json.loads((fixtures / "aim" / (stem + ".json")).read_text(encoding="utf-8"))
    assert data["annotation"]["cx"] == 160     # 960 - 800
    assert data["annotation"]["cy"] == 135     # 540 - 405
    assert data["annotation"]["size"] == 50    # 邊長不變
    assert 0 <= data["annotation"]["cx"] < 320
    assert 0 <= data["annotation"]["cy"] < 270


def test_source_path_is_not_persisted_into_fixture_json(parts):
    """source_path 是傳輸用欄位，不該汙染素材 schema（validate_annotation 沒有它）。"""
    client, src, fixtures = parts
    client.post("/api/annotate", json=_payload(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    data = json.loads((fixtures / "aim" / (stem + ".json")).read_text(encoding="utf-8"))
    assert "source_path" not in data


def test_annotate_rejects_source_path_outside_snapshots_root(parts, tmp_path):
    """路徑守門與 /snapshot 共用：不得拿它去讀 snapshots 以外的檔。"""
    client, src, fixtures = parts
    outside = tmp_path / "secret.png"
    ok, enc = cv2.imencode(".png", np.zeros((10, 10, 3), dtype=np.uint8))
    enc.tofile(str(outside))
    r = client.post("/api/annotate", json=_payload(str(outside)))
    assert r.status_code == 403


def test_annotate_does_not_leave_orphan_json_when_crop_fails(parts):
    """PNG 失敗必須整筆回錯——絕不留下沒有配對圖的孤兒 json（本次要修掉的狀態）。"""
    client, src, fixtures = parts
    missing = os.path.join(os.path.dirname(src), "does_not_exist.png")
    r = client.post("/api/annotate", json=_payload(missing))
    assert r.status_code == 404
    assert not (fixtures / "aim" / "does_not_exist.json").exists()


def test_annotate_without_source_path_still_works(parts):
    """向下相容：舊 client 沒帶 source_path 時仍寫 json（只是沒有配對圖）。"""
    client, src, fixtures = parts
    body = _payload(src)
    del body["source_path"]
    r = client.post("/api/annotate", json=body)
    assert r.status_code == 201
    assert r.json()["png"] is None


def test_annotate_html_sends_source_path():
    """前端要真的把 source_path 送出去，否則後端永遠走不到裁圖分支。"""
    from miningbot.web_static import render_annotate_html
    html = render_annotate_html("113", r"C:\snaps\a.png", (["Mythic"], ["原色"]))
    assert "source_path:" in html


# ── 還原（Ctrl+Z）───────────────────────────────────────────────────────────

def test_undo_removes_both_files_so_the_shot_requeues(parts):
    """標錯的補救：json + png 一起刪掉，那張快照才會重新排進佇列。"""
    client, src, fixtures = parts
    client.post("/api/annotate", json=_payload(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    r = client.post("/api/annotate/undo",
                    json={"image": os.path.basename(src), "category": "aim"})
    assert r.status_code == 200
    assert not (fixtures / "aim" / (stem + ".json")).exists()
    assert not (fixtures / "aim" / (stem + ".png")).exists()


def test_undo_is_404_when_nothing_was_written(parts):
    """沒有東西可刪就說沒有——不假裝還原成功。"""
    client, src, fixtures = parts
    r = client.post("/api/annotate/undo",
                    json={"image": "never_annotated.png", "category": "aim"})
    assert r.status_code == 404


def test_undo_refuses_path_traversal(parts, tmp_path):
    """只吃 basename：`../` 不得跳出 fixtures_dir（否則是任意檔案刪除）。"""
    client, src, fixtures = parts
    victim = tmp_path / "victim.json"
    victim.write_text("{}", encoding="utf-8")
    r = client.post("/api/annotate/undo",
                    json={"image": "../../victim.png", "category": "aim"})
    assert r.status_code == 404
    assert victim.exists()


def test_undo_refuses_when_json_is_older_than_window(parts):
    """Ctrl+Z 只救當下誤按：json mtime 超過視窗就回 409，一個檔都不刪。

    情境（2026-07-31 玩家）：素材已經 commit 進版控、頁面還開著，一個 Ctrl+Z 會變成
    沒人注意的 repo 刪除。時間視窗剛好編碼「剛剛按錯要重送」這個情境。
    """
    import time
    client, src, fixtures = parts
    client.post("/api/annotate", json=_payload(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    js = fixtures / "aim" / (stem + ".json")
    png = fixtures / "aim" / (stem + ".png")
    old = time.time() - 3600      # 一小時前，遠超過 15 分鐘視窗
    os.utime(str(js), (old, old))
    os.utime(str(png), (old, old))
    r = client.post("/api/annotate/undo",
                    json={"image": os.path.basename(src), "category": "aim"})
    assert r.status_code == 409
    assert "可還原" in r.json()["error"] or "時間" in r.json()["error"]
    assert js.exists(), "超時不得刪任何檔"
    assert png.exists()


def test_undo_allows_within_window(parts):
    """視窗內照樣刪——剛寫完立刻按 Ctrl+Z 是最常見的情形。"""
    import time
    client, src, fixtures = parts
    client.post("/api/annotate", json=_payload(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    js = fixtures / "aim" / (stem + ".json")
    png = fixtures / "aim" / (stem + ".png")
    recent = time.time() - 60      # 一分鐘前，在 15 分鐘視窗內
    os.utime(str(js), (recent, recent))
    os.utime(str(png), (recent, recent))
    r = client.post("/api/annotate/undo",
                    json={"image": os.path.basename(src), "category": "aim"})
    assert r.status_code == 200
    assert not js.exists() and not png.exists()
