"""傳送板偵測器：吃一張回礦方位全幀，回 ``(x, y, score)`` 或 `None`。

回礦介入時玩家要在八方位圖裡找 Teleportation Board 點下去。這支的工作是**猜**
它在哪——只做建議，永遠不自動點（H043 虛空墜落是全自動那條路的代價）。

入口形狀先於實作定下來（2026-07-28）：沒有量尺就沒法調，所以
`build_reentry_dataset --eval` 的評估報告先立起來，回空時報告照樣完整成立
（0% 命中而不是拋例外）。實作見 `detect`。
"""

from __future__ import annotations


def detect(frame):
    """回 ``(x, y, score)``＝畫面上最像傳送板的位置與分數；找不到回 `None`。

    純函式、不做 I/O；門檻／ROI／面積夾全放 `Config`。
    """
    return None
