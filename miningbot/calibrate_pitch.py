"""校準 CLI：量出「挖礦標準角」sweep_pitch_center_back_px（spec 2026-07-17）。

用法（站在礦內、Roblox 開著；console 與遊戲來回切換）：
  uv run python -m miningbot.calibrate_pitch

互動指令（每步先自動聚焦回遊戲、游標移進畫面、沉澱後才拖曳）：
  r         歸位到夾限（累計回拉量歸 0；一切從絕對基準起算）
  u [px]    向上拉 px（預設 sample_pitch_step_px）
  d [px]    向下拉 px（已在夾限再往下只會飽和，記帳同步夾 0）
  q         結束並印最終值

畫面滿意時把印出的「累計回拉量」寫回 config.sweep_pitch_center_back_px。
"""
import re
import time
from dataclasses import dataclass, field

from . import input_control as ic
from .config import DEFAULT as cfg


def parse_calib_command(text: str, default_step: int):
    """互動指令解析（純函式；寧可不動不誤動，解析不出回 None）。"""
    parts = (text or "").strip().lower().split()
    if not parts:
        return None
    head = parts[0]
    if head in ("q", "quit") and len(parts) == 1:
        return ("quit", 0)
    if head in ("r", "reset") and len(parts) == 1:
        return ("reset", 0)
    if head in ("u", "up", "d", "down"):
        kind = "up" if head in ("u", "up") else "down"
        if len(parts) == 1:
            return (kind, default_step)
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
            return (kind, int(parts[1]))
        return None
    return None


def apply_calib_step(offset: int, kind: str, px: int) -> int:
    """累計回拉量記帳（純函式）。reset＝回夾限（0）；up＝+px；down＝-px 但夾 0——
    物理事實：已在夾限再往下拖只會飽和，記負值＝記帳與實際角度脫鉤。"""
    if kind == "reset":
        return 0
    if kind == "up":
        return offset + px
    return max(0, offset - px)


def parse_calib_target(args: tuple):
    """`校準 [挖礦|回礦]` 目標角解析（純函式）。無參數預設挖礦；解析不出回 None。"""
    if not args:
        return "mining"
    a = args[0].lower()
    if a in ("挖礦", "mining"):
        return "mining"
    if a in ("回礦", "reentry"):
        return "reentry"
    return None


def can_accept_calibration(reentry_active: bool, already_calibrating: bool):
    """校準接受閘（純函式）。回礦 episode 進行中／已在校準中一律拒絕（spec 第 1 節）。"""
    if already_calibrating:
        return False, "已在校準中（校準卡按 ❌ 可離開）"
    if reentry_active:
        return False, "回礦 episode 進行中——結束後再校準"
    return True, ""


# ---- Discord 遠端校準（2026-07-18 spec）：純決策，I/O 全在 main ----
CALIB_TITLE = "🎯 俯仰校準"       # 跨重啟掃頻道辨識殘留卡用——不可改字（比照 _REMOTE_TITLE）
CALIB_STEPS = (1, 5, 10, 50)
CALIB_EMOJIS = ("⬆️", "⬇️", "🔁", "🧭", "📷", "💾", "❌")
CALIB_ACTIONS = dict(zip(CALIB_EMOJIS,
                         ("up", "down", "step", "home", "snap", "save", "exit")))


@dataclass
class CalibSession:
    """校準 session 記帳（主迴圈持有；輪詢執行緒只讀 message_id/reactions_seen）。"""
    target: str                              # "mining" | "reentry"
    offset: int                              # 夾限上 px（絕對記帳，pitch_reset 基準）
    step: int = 5
    prev_paused: bool = False                # 進場前 paused；❌ 離開時恢復
    message_id: str | None = None
    reactions_seen: dict = field(default_factory=dict)


def next_step(cur: int) -> int:
    """幅度循環 1→5→10→50→1；非法現值回 1（防壞記帳卡死切換）。"""
    if cur not in CALIB_STEPS:
        return CALIB_STEPS[0]
    return CALIB_STEPS[(CALIB_STEPS.index(cur) + 1) % len(CALIB_STEPS)]


def calib_field_names(target: str) -> tuple[str, str]:
    """目標角 → (back_px 欄名, clamp 欄名)。spec 第 0 節映射表。"""
    if target == "mining":
        return "sweep_pitch_center_back_px", "sweep_pitch_clamp_px"
    return "reentry_pitch_back_px", "reentry_pitch_clamp_px"


def build_calib_embed(target: str, offset: int, config_value: int,
                      step: int, warn: str = "") -> dict:
    """校準卡 embed（純函式）。所有可變狀態（offset/幅度/現值）都進 description。"""
    name = "挖礦標準角" if target == "mining" else "回礦標準角"
    fld, _ = calib_field_names(target)
    desc = (
        (f"⚠ {warn}\n\n" if warn else "")
        + f"**目標角**：{name}（`{fld}`）\n"
        + f"**目前**：夾限上 {offset}px（config 現值 {config_value}px）\n"
        + f"**幅度**：{step}px（🔁 循環 1→5→10→50）\n\n"
        + "⬆️ 上調　⬇️ 下調（夾限飽和記帳夾 0）　🧭 歸位到夾限\n"
        + "📷 截圖　💾 寫回 config　❌ 離開\n"
    )
    return {"title": CALIB_TITLE, "description": desc, "color": 0x5865F2,
            "footer": {"text": "每次調整會重貼此卡（反應歸零可再點）並附新截圖"}}


def rewrite_config_value(text: str, field_name: str, new_value: int):
    """把 config.py 內 `<field>: int = <數字>` 這一行的數字換成 new_value（純函式）。

    錨點必須恰好出現一次，否則回 None（不硬寫；spec 第 3 節——寫錯 config 比不寫
    更糟）。只動數字本身，行首縮排與行尾註解 byte-level 保留。
    """
    pattern = re.compile(
        rf"(?m)^(?P<head>\s*{re.escape(field_name)}: int = )(?P<val>\d+)(?P<tail>.*)$")
    if len(pattern.findall(text)) != 1:
        return None
    return pattern.sub(
        lambda m: f"{m.group('head')}{new_value}{m.group('tail')}", text)


def _focus_and_settle():
    """找 Roblox → 最大化 → 前景 → 游標移進畫面 → 沉澱（拖曳前必要沉澱：
    焦點剛切回就送右鍵拖曳會被吃，見 sampler_pitch_focus_settle_s 註解）。
    校準有人在場，聚焦失敗印提示請人手點一下即可——不搬 main._focus_roblox
    的 AttachThreadInput 補救，CLI 保持薄。"""
    import ctypes
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, cfg.window_title)
    if not hwnd:
        raise SystemExit(f"找不到 Roblox 視窗（title={cfg.window_title}）；先開好遊戲")
    u.ShowWindow(hwnd, 3)      # SW_MAXIMIZE（不可 SW_RESTORE——會縮窗座標全錯）
    time.sleep(0.3)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    if u.GetForegroundWindow() != hwnd:
        print("⚠ 未取得前景焦點——請手動點一下遊戲視窗後重送指令")
    ic.move_to(cfg.screen_w // 2, cfg.screen_h // 2)
    ic.settle(cfg.sampler_pitch_focus_settle_s)


def main():
    print(__doc__)
    offset = None                          # None＝尚未 r 歸位（無絕對基準不准微調）
    while True:
        try:
            line = input("calibrate-pitch> ").strip()
        except EOFError:
            break
        cmd = parse_calib_command(line, cfg.sample_pitch_step_px)
        if cmd is None:
            print("指令：r（歸位）/ u [px] / d [px] / q（結束）")
            continue
        kind, px = cmd
        if kind == "quit":
            break
        if kind != "reset" and offset is None:
            print("先 r 歸位到夾限（絕對基準），再微調")
            continue
        _focus_and_settle()
        if kind == "reset":
            ic.pitch_reset(cfg.sweep_pitch_clamp_px, 0)
            offset = 0
        else:
            ic.pitch_nudge(-px if kind == "up" else px)   # 上＝dy<0（沿用取樣視窗語意）
            offset = apply_calib_step(offset, kind, px)
        print(f"累計回拉量（夾限→現在）= {offset}px")
    if offset is not None:
        print(f"最終：sweep_pitch_center_back_px = {offset}")


if __name__ == "__main__":
    main()
