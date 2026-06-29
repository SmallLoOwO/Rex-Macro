from dataclasses import dataclass
from enum import Enum

class State(Enum):
    MINING = "MINING"
    HARVESTING = "HARVESTING"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    RESET_WAIT = "RESET_WAIT"      # 礦坑重置中：停止挖礦、等使用者重新定位（chill 仍可搶先）

@dataclass
class Observation:
    chill_audio: bool
    chill_text: bool
    harvest_done: bool
    harvest_failed: bool
    human_cleared: bool
    mine_resetting: bool = False   # OCR 偵測到「mine will reset in」

def decide_transition(state: State, o: Observation) -> State:
    if state is State.MINING:
        if o.chill_audio and o.chill_text:   # 稀有優先（雙重確認）
            return State.HARVESTING
        if o.mine_resetting:                 # 偵測到重置 → 暫停等定位
            return State.RESET_WAIT
        return State.MINING
    if state is State.HARVESTING:
        if o.harvest_failed:
            return State.NEEDS_HUMAN
        if o.harvest_done:
            return State.MINING
        return State.HARVESTING
    if state is State.NEEDS_HUMAN:
        return State.MINING if o.human_cleared else State.NEEDS_HUMAN
    if state is State.RESET_WAIT:
        if o.chill_audio and o.chill_text:   # 例外：重置期間意外出現稀有 → 強制採集
            return State.HARVESTING
        if o.human_cleared:                  # 使用者重新定位後按 Q
            return State.MINING
        return State.RESET_WAIT
    return state


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


def toggle_pause_action(paused: bool, state: State) -> str:
    """Q 鍵的行為決策（純函式）：決定按 Q 時要走哪條路。

    回傳 'resume' / 'clear_human' / 'pause'：
    - 目前暫停中 → 'resume'（解除暫停，重新握住 W+左鍵）
    - 處於 NEEDS_HUMAN / RESET_WAIT → 'clear_human'（清人工旗標，等同「已處理完」）
    - 否則 → 'pause'（標準暫停）

    抽出原因：3 個分支的條件易寫錯（例如把 NEEDS_HUMAN 與 paused 合併判斷、
    或誤把 RESET_WAIT 漏掉），純函式可直接斷言每個 (paused, state) 組合的行為。
    分支優先序：paused 先判（即使處於 NEEDS_HUMAN 同時也被暫停，先 resume）。
    """
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
