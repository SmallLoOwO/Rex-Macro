"""WebSocket 訊息協議：dataclass、序列化、座標還原（純函式）。

訊息分兩種 type：
- "event"（bot → web）：NEEDS_HUMAN / HARVEST_SUCCESS / REENTRY_START / 狀態變動 等
- "command"（web → bot）：fire_at / reentry_click / config_set / pause / request_frame 等

座標系：所有 (x,y) 都是**遊戲原生解析度**（1920×1080）；client 端用 CSS scale 顯示，
點擊座標 server 端用 client_to_native_coords 還原（Task 3）。
"""
import json
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class WebMessage:
    """WebSocket 訊息。type 必為 "event" 或 "command"；payload 是 dict。

    frozen=True：訊息不可變，避免 consumer 改到 producer 還在用的實例。
    """
    type: str
    payload: dict


def serialize_message(msg: WebMessage) -> str:
    """WebMessage → JSON 字串（ WebSocket text frame 傳輸用）。"""
    return json.dumps(asdict(msg), ensure_ascii=False)


def parse_message(text: str) -> WebMessage | None:
    """JSON 字串 → WebMessage；不合法回 None（不丟例外，避免網路層吃壞資料炸掉）。

    缺 type / 缺 payload / type 不是字串 / payload 不是 dict 一律 None。
    """
    try:
        d = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    t = d.get("type")
    p = d.get("payload")
    if not isinstance(t, str) or not isinstance(p, dict):
        return None
    return WebMessage(type=t, payload=p)


def client_to_native_coords(
    client_xy: tuple[float, float],
    canvas_size: tuple[int, int],
    native_size: tuple[int, int],
    pan_offset: tuple[float, float] = (0.0, 0.0),
    zoom: float = 1.0,
) -> tuple[int, int]:
    """把玩家在 canvas 上點的座標還原成遊戲原生解析度座標。

    參數：
    - client_xy：玩家點擊的 canvas 座標（像素）
    - canvas_size：canvas 在瀏覽器中顯示的尺寸（CSS 像素）
    - native_size：遊戲原生解析度（1920×1080）
    - pan_offset：玩家 pinch-zoom 後平移的量（在 native 空間的位移；預設 (0,0)）
    - zoom：玩家 pinch-zoom 的倍數（1.0 = fit canvas；2.0 = 放大 2x）

    順序：先除 zoom（退到未 zoom 座標）→ scale 到 native → 加 pan_offset → clamp。

    pan_offset 的定義是「玩家把原圖往哪個方向拖了多少 native 像素」——client 端
    會在 event handler 裡追蹤，並跟 client_xy 一起送 server。本函式純數學，
    不處理 client 端手勢。

    clamp 到 [0, native_w-1] / [0, native_h-1]：避免玩家平移出界送了負值或超界。
    """
    cx, cy = client_xy
    cw, ch = canvas_size
    nw, nh = native_size
    px, py = pan_offset

    # 先除 zoom：zoom 是「顯示放大」，反向除掉
    unzoomed_x = cx / zoom
    unzoomed_y = cy / zoom

    # canvas → native 比例縮放
    scale_x = nw / cw
    scale_y = nh / ch
    native_x = unzoomed_x * scale_x + px
    native_y = unzoomed_y * scale_y + py

    # clamp
    native_x = max(0, min(native_x, nw - 1))
    native_y = max(0, min(native_y, nh - 1))
    return (int(native_x), int(native_y))


def _parse_pointer_payload(payload: dict, canvas_size: tuple,
                           native_size: tuple, expected_cmd: str,
                           id_keys: tuple[str, ...]) -> dict | None:
    """fire_at / reentry_click 共用解析：驗證 cmd/flow/id + 還原座標。

    id_keys：可接受的 id 欄位名（fire_at 收 harvest_id 或 attempt_id；
    reentry_click 只收 attempt_id）；取第一個非 None 的。
    """
    if payload.get("cmd") != expected_cmd:
        return None
    flow = payload.get("flow")
    if not isinstance(flow, str) or not flow:
        return None
    ep_id = None
    for k in id_keys:
        v = payload.get(k)
        if isinstance(v, str) and v:
            ep_id = v
            break
    if ep_id is None:
        return None
    cxy = payload.get("client_xy")
    if not isinstance(cxy, (list, tuple)) or len(cxy) != 2:
        return None
    try:
        cx, cy = float(cxy[0]), float(cxy[1])
    except (TypeError, ValueError):
        return None
    zoom = payload.get("zoom", 1.0)
    try:
        zoom = float(zoom)
        if zoom <= 0:
            return None
    except (TypeError, ValueError):
        return None
    pan = payload.get("pan_offset", [0, 0])
    if not isinstance(pan, (list, tuple)) or len(pan) != 2:
        return None
    try:
        px, py = float(pan[0]), float(pan[1])
    except (TypeError, ValueError):
        return None
    x, y = client_to_native_coords(
        client_xy=(cx, cy), canvas_size=canvas_size, native_size=native_size,
        pan_offset=(px, py), zoom=zoom,
    )
    out = {"flow": flow, "x": x, "y": y}
    # 把符合的 id 欄位原樣回填
    for k in id_keys:
        v = payload.get(k)
        if isinstance(v, str) and v:
            out[k] = v
            break
    return out


def parse_fire_at_payload(payload: dict, canvas_size: tuple,
                          native_size: tuple = (1920, 1080)) -> dict | None:
    """解析 fire_at 命令；不合法回 None。

    接受 harvest_id（harvest flow）或 attempt_id（reentry flow）。
    """
    return _parse_pointer_payload(
        payload, canvas_size, native_size, "fire_at",
        id_keys=("harvest_id", "attempt_id"),
    )


def parse_reentry_click_payload(payload: dict, canvas_size: tuple,
                                native_size: tuple = (1920, 1080)) -> dict | None:
    """解析 reentry_click 命令；不合法回 None。只接受 attempt_id。"""
    return _parse_pointer_payload(
        payload, canvas_size, native_size, "reentry_click",
        id_keys=("attempt_id",),
    )
