from dataclasses import dataclass
from enum import Enum

class State(Enum):
    MINING = "MINING"
    HARVESTING = "HARVESTING"
    NEEDS_HUMAN = "NEEDS_HUMAN"

@dataclass
class Observation:
    chill_audio: bool
    chill_text: bool
    harvest_done: bool
    harvest_failed: bool
    human_cleared: bool

def decide_transition(state: State, o: Observation) -> State:
    if state is State.MINING:
        if o.chill_audio and o.chill_text:   # 雙重確認才接管
            return State.HARVESTING
        return State.MINING
    if state is State.HARVESTING:
        if o.harvest_failed:
            return State.NEEDS_HUMAN
        if o.harvest_done:
            return State.MINING
        return State.HARVESTING
    if state is State.NEEDS_HUMAN:
        return State.MINING if o.human_cleared else State.NEEDS_HUMAN
    return state
