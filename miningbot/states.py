from dataclasses import dataclass
from enum import Enum

class State(Enum):
    MINING = "MINING"
    HARVESTING = "HARVESTING"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    RESET_WAIT = "RESET_WAIT"      # 礦坑重置中：停止挖礦、等使用者重新定位（chill 仍可搶先）
    REENTRY = "REENTRY"            # 重置後自動回礦：回地表→找面板→點層級按鈕（失敗 reroll）

@dataclass
class Observation:
    chill_audio: bool
    chill_text: bool
    harvest_done: bool
    harvest_failed: bool
    human_cleared: bool
    mine_resetting: bool = False   # OCR 偵測到「mine will reset in」
    reset_complete: bool = False   # RESET_WAIT 中 banner reset 字樣已消失＋沉澱夠久
    reentry_done: bool = False     # _tick_reentry 回報成功（已回礦內）
    reentry_failed: bool = False   # reroll 用盡（→ NEEDS_HUMAN）
    auto_reenter: bool = False     # 任一回礦模式（remote/auto）啟用（Bot._reentry_active()；off＝RESET_WAIT 維持今日等人工行為）
    manual_reentry: bool = False   # Discord `回礦` 指令/STUCK 🏠 反應：手動觸發回礦（H044 spec 第 3 節）

def decide_transition(state: State, o: Observation) -> State:
    if state is State.MINING:
        if o.chill_audio and o.chill_text:   # 稀有優先（雙重確認）
            return State.HARVESTING
        if o.mine_resetting:                 # 偵測到重置 → 暫停等定位（回礦由重置流程接手）
            return State.RESET_WAIT
        if o.manual_reentry and o.auto_reenter:   # 手動回礦（蒐集素材/卡死自救，用途不限）
            return State.REENTRY
        return State.MINING
    if state is State.HARVESTING:
        # H051：重置 pending（RESET_WAIT 因 chill 轉入、或 MINING 同幀 chill 搶先）時
        # 收尾一律回 RESET_WAIT——礦坑倒數中/已清場，NEEDS_HUMAN 會卡死（banner worker
        # 不在該狀態跑、無人清旗標），MINING 則對著已重置的礦坑空挖。回 RESET_WAIT
        # 讓既有 reset_complete → REENTRY 鏈接手。進行中（尚無成敗）不被打斷。
        if o.harvest_failed:
            return State.RESET_WAIT if o.mine_resetting else State.NEEDS_HUMAN
        if o.harvest_done:
            return State.RESET_WAIT if o.mine_resetting else State.MINING
        return State.HARVESTING
    if state is State.NEEDS_HUMAN:
        if o.manual_reentry and o.auto_reenter:   # 手動優先於 human_cleared（更明確的意圖）
            return State.REENTRY
        return State.MINING if o.human_cleared else State.NEEDS_HUMAN
    if state is State.RESET_WAIT:
        if o.chill_audio and o.chill_text:   # 例外：重置期間意外出現稀有 → 強制採集
            return State.HARVESTING
        if o.manual_reentry and o.auto_reenter:   # 人工強制：繞過 reset_complete（凍結逃生口）
            return State.REENTRY
        if o.human_cleared:                  # 使用者重新定位後按 Q＝明確接手，優先於自動路徑
            return State.MINING
        if o.auto_reenter and o.reset_complete:
            return State.REENTRY
        return State.RESET_WAIT
    if state is State.REENTRY:
        if o.reentry_failed:                 # failed 先判：同 tick 兩旗標並存時保守交人工
            return State.NEEDS_HUMAN
        if o.reentry_done:
            return State.MINING
        return State.REENTRY
    return state


def should_notify_spawn_chill(state: State, chill_audio: bool, chill_text: bool,
                              already_notified: bool) -> bool:
    """spawn chill 通知決策（純函式）：chill 確認 + 處於挖不到的狀態 → 該通知。

    「spawn chill」＝礦坑刷新時稀有礦生在預設方塊中。此時 chill 音效照樣響，
    但 bot 一定處於挖不到該 礦的狀態：
    - NEEDS_HUMAN：等人工（可能在王座/地表），不在 礦坑可挖區；
    - REENTRY：傳送回礦途中，鏡頭/裝備都還沒就位。
    這兩個狀態 decide_transition 不會因 chill 轉 HARVESTING（挖了也白挖），
    故只發 Discord 通知請主人手動處理。

    already_notified 由呼叫端做 episode 去抖動：同一波 chill（chill_audio 持續為真）
    只通知一次；chill_audio 回落時呼叫端重置旗標，下一波再觸發可再通知。
    RESET_WAIT 不算 spawn chill——它 chill 會直接轉 HARVESTING 強採（見上）。
    """
    if not chill_audio or not chill_text:
        return False
    if already_notified:
        return False
    return state in (State.NEEDS_HUMAN, State.REENTRY)


def resolve_state_transition(current: State, decided: State,
                             entered: "State | None") -> State:
    """主迴圈的 state-commit 決策（純函式，給測試鎖定）。

    抽出來的原因：這塊邏輯 inline 在 run() loop 時曾是 bug 溫床——一次 refactor
    把它寫成 `new_state = self.state`（讀 current 而非 decided），結果 chill 觸發的
    HARVESTING 被 commit 回 MINING，稀有礦完全不採。decide_transition 本身正確、
    測試全綠，但這層「commit 邏輯」沒被覆蓋到。抽成純函式後：

    - current 不出現在返回值計算裡（除非 entered/decided 等於 current），
      從根斷絕「讀錯變數」這個 bug 類別。
    - 測試能直接斷言「decide_transition 回什麼，commit 就要是什麼」，
      不必跑整個 I/O 迴圈。

    Args:
      current: 呼叫 decide_transition 前的 self.state（僅 reference，不參與決策）
      decided: decide_transition(current, obs) 的回傳值
      entered: _on_enter(decided, frame) 的回傳值
               None = 接受 decided；非 None = 降級（如 MINING 入口聚焦失敗 → NEEDS_HUMAN）

    Returns:
      最終應 commit 到 self.state 的 State。
    """
    if entered is not None and entered != decided:
        return entered          # _on_enter 要求降級（聚焦失敗等）
    return decided              # 預設：接受 decide_transition 的判斷


def toggle_pause_action(paused: bool, state: State, startup_phase: bool = False) -> str:
    """Q 鍵的行為決策（純函式）：決定按 Q 時要走哪條路。

    回傳 'skip_env' / 'resume' / 'clear_human' / 'pause'：
    - 啟動環境檢查階段 → 'skip_env'（跳過剩餘 UI 前置檢查直接開挖；程式重開環境沒變時
      的快速啟動。原 F8 專用鍵與 Roblox 內建功能衝突而廢棄，2026-07-10 改沿用 Q——
      貼使用者「暫停重新繼續」直覺、零新鍵）
    - 目前暫停中 → 'resume'（解除暫停，重新握住 W+左鍵）
    - 處於 NEEDS_HUMAN / RESET_WAIT → 'clear_human'（清人工旗標，等同「已處理完」）
    - 否則 → 'pause'（標準暫停）

    抽出原因：分支條件易寫錯（例如把 NEEDS_HUMAN 與 paused 合併判斷、
    或誤把 RESET_WAIT 漏掉），純函式可直接斷言每個組合的行為。
    分支優先序：startup_phase 最先（啟動中按 Q 的唯一合理語意就是跳過；此時
    paused/state 都還不是穩定值），再 paused（即使處於 NEEDS_HUMAN 同時也被暫停，先 resume）。
    """
    if startup_phase:
        return "skip_env"
    if paused:
        return "resume"
    if state in (State.NEEDS_HUMAN, State.RESET_WAIT):
        return "clear_human"
    return "pause"


def is_blocked_from_mining(state: State, paused: bool) -> bool:
    """判斷目前是否處於 `!resume` 可恢復的阻塞狀態（純函式）。

    回傳 True 的情況（!resume 會做對應恢復，回覆「已收到」）：
    - NEEDS_HUMAN：清 human_cleared，下個 tick 跳 MINING
    - RESET_WAIT：同上
    - paused=True：解除暫停
    回傳 False（MINING + 非暫停 = 已在挖，!resume 是無效操作；回覆「不需要恢復」）。
    """
    return paused or state in (State.NEEDS_HUMAN, State.RESET_WAIT)


def can_consume_ability(state: State) -> bool:
    """Discord `ability` 指令（遠端按一次 X）的主迴圈消費閘（純函式）。

    回傳 True：MINING / NEEDS_HUMAN / RESET_WAIT —— 按一下 X 安全、不干擾其他流程。
    回傳 False：HARVESTING / REENTRY —— sweep/開火/回礦導航進行中插按鍵會打亂時序，
    旗標留著不消費，回到可消費狀態（MINING 等）後自然執行。
    """
    return state not in (State.HARVESTING, State.REENTRY)


def can_accept_manual_reentry(state: State, reentry_active: bool) -> tuple[bool, str]:
    """Discord `回礦` 指令／STUCK 🏠 的接收守門（純函式）。回 (可接受, 拒絕原因)。

    HARVESTING 拒收：採集有自己的超時/giveup 路徑，插入回礦會亂時序；也不排隊
    （比照 aim-reply「不排隊，避免舊指令補刀」）。REENTRY 拒收：已在流程中。
    """
    if not reentry_active:
        return False, "回礦模式未啟用（reentry_mode=off 或按鈕座標未校準）"
    if state is State.HARVESTING:
        return False, "採集進行中，稍後再送"
    if state is State.REENTRY:
        return False, "已在回礦流程中（用 重骰/跳過/📷 控制）"
    return True, ""


def update_capacity_streak(streak: int, pct: float | None,
                           threshold: float) -> tuple[int, bool]:
    """Capacity 連續 ≥ 門檻計數（只供加速 banner 輪詢與去抖 log；純函式）。

    - pct is None（本輪 OCR 讀失敗）→ streak 原樣、不觸發（單次讀失敗不重計）。
    - pct >= threshold → streak+1；新 streak >= 2 → 觸發（連續兩次確認）。
    - pct < threshold → 歸零、不觸發。
    """
    if pct is None:
        return streak, False
    if pct >= threshold:
        new_streak = streak + 1
        return new_streak, new_streak >= 2
    return 0, False
