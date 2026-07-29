# 雙 chill 對帳：一場響兩聲只進帳一顆就結案

日期：2026-07-30
狀態：設計待資料（**門檻不可先寫死**——見 Blocked On）
關聯：`2026-07-30-prechill-evidence-cache-design.md`（**前置**，提供上升緣時間戳與面板裁圖）、
`2026-07-30-giveup-rescue-already-mined-design.md`（共用面板名字剖析）、
incident 072（`decide_post_success` 續採）、H060（防掛機跳躍音誤觸 chill）

## Problem Statement

同一個 chill episode 內可能響第二聲＝第二顆稀有礦。現況三個缺口疊在一起：

1. **第二聲完全蒸發。** HARVESTING 中再響一次只會多印一行「chill 觸發」——沒有計數、
   沒有事件、沒有通知。`_check_spawn_chill`（`main.py:1184`）只覆蓋 `NEEDS_HUMAN`／`REENTRY`。
   實錄：07-29 14:43:58 chill 進 harvest 123，**14:44:14 又響一次**，之後整場沒有再提到它。

2. **續採只看當下那一幀。** `harvester.decide_post_success`（`harvester.py:193`）拿的是
   成功後 `find_tracker` 在**當前視野**的結果，加一個 100px 距離閘擋剛採掉的殘影。
   不重掃八方位 → 第二顆在別的方位就必漏。

3. **漏了也不會有人知道。** `decide_sweep_failure(extra_mode=True)` 全空回 `EXIT_SUCCESS`，
   安靜收工回 MINING。這個行為本身是對的（不該為了 bonus 框交人工），但它也讓
   「其實還有一顆」這件事完全沒有出口。

使用者的要求是**帳要對得上**：響兩聲就該進帳兩顆，只進帳一顆就結案是問題。

## Blocked On

**上升緣 debounce 門檻現在沒有任何資料可以填。**

`listener.latest_score()` 是滾動比對，同一聲會連續多個 tick 都在
`cfg.audio_match_threshold` 之上（07-22 01:43:31~33 三秒七行是同一聲）。要分辨「兩聲」
必須數分數**回落到門檻下再上來**的次數，而現在的 log 只印觸發、不印回落。

`2026-07-30-prechill-evidence-cache-design.md` 的 B 段就是為了產生這份分布。
**收滿一週實機資料、看得到上升緣與回落的實際間隔之後**，才回來填本 spec 的
`chill_edge_release_s`。在那之前不要接通知——門檻猜錯會直接製造新的人工次數，
與「只做保守救援」的方向相衝。

已知的一個真實間隔：14:43:58 → 14:44:14，**16 秒**。重疊 <2s 的兩聲，
現在的分數形狀分不出來，需要資料才知道那種情況存不存在。

## Solution

### 進帳數怎麼算

episode 開場（`_on_enter(State.HARVESTING)`）與收尾（`_harvest_resume_mining()` 或
`_harvest_giveup()`）各裁一張 `cfg.backpack_review_region`，跑
`2026-07-30-giveup-rescue-already-mined-design.md` 的名字剖析，
差分後濾掉 `common_ore_names()`，得到本 episode 的**進帳非-common 礦名數**。

為什麼用面板而不是數上升緣：面板是狀態，不會淡出、不需要 hover、不受前景影響。
數上升緣只知道響了幾聲，不知道實際到手幾顆。

已知天花板（與救援 spec 相同）：同一 filter 零點之後第二次挖到同一礦種時，
名字已在、只有數量 +1，而數量欄在 craft 面板開著時會讀到配方需求而不是存量。
**兩顆同礦種的雙 chill 因此會被算成一顆。** 這是已知漏判，不是錯判——寧漏勿誤。

### 對帳規則

```
上升緣數 ≥ 2  且  進帳非-common 礦名數 < 上升緣數   →  帳不平
```

帳不平 → 交人工通知（使用者裁決：「這是特殊事件，我認為加上人工是可以的」）。
通知內容要能讓人一眼判斷，至少包含：上升緣時間戳與分數、進帳礦名、
episode 開場與收尾的面板裁圖、以及最後一輪的八方位掃描圖。

帳平 → 照現行流程收尾，只在 `harvest.log` 記一筆對帳結果。

### 三種真因分不開，所以不猜

「響兩聲只進帳一顆」至少有三種來源，證據上分不開：

1. 第二顆在別的方位沒掃到（bot 的錯）
2. 第二顆被別的玩家挖走（不是錯）
3. 第二聲是同一顆的重播或誤觸（H060 那類）

本 spec **不嘗試分辨**，一律通知人工由使用者判斷。要降低第 3 類的量，靠的是
H060 既有的防掛機靜音（`audio.chill_muted_after_antiafk`）在上升緣判定之前套用，
以及之後用實機資料調 `chill_edge_release_s`。

### 沒有採用的選項

**「雙 chill 就在成功後強制重掃一輪八方位」**（成本 ~20s，且
`decide_sweep_failure(extra_mode=True)` 全空已經是 `EXIT_SUCCESS`、不會製造新的人工）
技術上安全，但使用者要的是帳目對得上而不是多掃一輪。留作後續選項：
若實機資料顯示帳不平大多是「第二顆在別方位」（真因 1），再把重掃接在通知之前，
掃到就自己處理、掃不到才通知。

## Config

```python
chill_edge_release_s: float = 0.0    # 分數要回落多久才算下一次上升緣；0 = 停用對帳
chill_reconcile_enabled: bool = False
```

兩個都預設關。`chill_edge_release_s` 的初值**必須**由前置 spec 的實機分布決定，
不可憑感覺填。

## Testing

純函式先測：

- 上升緣序列 → 對帳判定：給 `(上升緣數, 進帳礦名數)` 的各種組合，驗證帳平／帳不平；
  上升緣數 <2 時一律帳平（單聲 chill 不進對帳）。
- debounce：給一串 `(時間戳, 分數)`，驗證在不同 `chill_edge_release_s` 下數出的上升緣數；
  含「連續多 tick 在門檻上算一次」與「回落不足 release 時間不算新的一聲」。
- 面板進帳計數沿用救援 spec 的剖析與差分函式，不重寫第二份。

## Further Notes

- 對帳只在 HARVESTING episode 內有意義。MINING 期間響的 chill 就是新 episode 的起點，
  不進對帳。
- `self._chill_edges` 的清空點是 `_on_enter(MINING)`（見前置 spec），
  所以「採集成功回 MINING 後又立刻 chill」會正確開新的一場。
- 對帳通知是**新增的人工次數來源**。上線後要跟救援 spec 的 `HARVEST_RESCUED` 一起看
  淨值：救援省下的人工次數要大於對帳新增的，否則整體是退步。
