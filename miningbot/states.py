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
