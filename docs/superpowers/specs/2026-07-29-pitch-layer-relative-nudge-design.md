# 失敗路徑俯仰層轉換：clamp reset 改「相對 nudge」（flag-gated）

日期：2026-07-29
狀態：設計定案，待實作（**第一個任務是實機驗證，不是寫碼**——見 D1）
關聯：`2026-07-28-sweep-pitch-enable-design.md`（啟用俯仰層掃描，本 spec 的前置）、
`2026-07-11-pitch-sweep-design.md`（原始設計，`_pitch_layer_transition` 已實作）、
H065（`execute_scan` 的 D2 toggle 守門，已 commit `0736f7c`，本 spec 假設它已實機驗證）

## Problem Statement

俯仰層掃描「啟用」之後，每次層轉換都跑完整的 `pitch_reset(1500, 370)`——拖到夾限飽和
再回拉 370 到挖礦標準角，然後才 nudge 到上／下層。這個 clamp reset 在 harvest 121 實測
燒掉 **31s（mid→up）＋44s（up→down）＝75s，佔整場 267s 的 28%**。

但 clamp reset 唯一多換到的東西是「重新錨到絕對 standard 角」——只有當掃描中途俯仰**漂移**
時才需要。開闊洞裡旋轉（`,`／`.`）不改俯仰、不撞牆，掃完一輪俯仰還在 standard，clamp reset
是純浪費；窄坑道裡相機撞牆才可能漂，那時 clamp reset 才是必要保險。現狀不分場合一律 reset，
開闊洞白等 75s。

玩家要的是：開闊洞時省掉這 75s，窄坑道時仍保有 clamp reset 的保險。

## Solution

把「clamp reset＋nudge」與「純相對 nudge」兩條路並存，用一個 config 開關切換，
**預設關（＝今日行為不變）**。開啟時層轉換跳過 clamp reset，改用相對 nudge 從當下位置
（假設＝standard）移到目標層；關閉時逐字回到今日的 clamp reset＋nudge。

相對 nudge 用「**up → mid → down**」兩步式（每步 ±`sweep_pitch_step_px`），**不用**
mid→up、up→down（+370）的單步直達——後者假設 drag 線性（370 = 2×185），而指標加速
曲線保證不了、離線也量不到（見 Further Notes「量測死路」），兩步式每步都是 ±185、
對稱是構造保證、不碰線性。

**漂移風險不在碼裡解決，在實機解決**：相對 nudge 假設「掃描中途俯仰不漂」。這個假設對不對
隨場次變（開闊洞＝對，窄坑道＝錯），無法離線判定。所以 spec 把「實機驗證相對 nudge 在
玩家的典型礦場會不會落地正確」訂為**第一個、且 gating 的任務**——驗不過就保持開關預設關，
clamp reset 留著當保險，零回歸。

## User Stories

1. 作為玩家，我想在開闊礦洞裡掃俯仰層時省掉那 75s 的鏡頭歸位，這樣全空場次早 75s 收場。
2. 作為玩家，我想在窄坑道（相機撞牆）裡仍保有 clamp reset 的絕對歸位，這樣俯仰不會因漂移
   落到未知角、對著地板開火。
3. 作為玩家，我想在「不確定安不安全」時一鍵關回今日行為，這樣我能隨時退回保險設定。
4. 作為玩家，我想在 up 層掃完後鏡頭直接往下到 down 層，不要先甩到夾限再拉回（那個動作
   看起來像在「矯正」、很奇怪）。
5. 作為玩家，我想在採集收尾後視角仍回到置中標準角，這樣我接手時畫面不是歪的。
6. 作為玩家，我想知道 bot 現在是走相對 nudge 還是 clamp reset，這樣我判讀 log 時分得清楚。
7. 作為 bot 操作者，我想讓「相對 nudge 假設不漂」這件事被一場真實場次驗證，而不是靠推理，
   這樣開關預設值是實測來的、不是猜的。
8. 作為 bot 操作者，我想讓 up 與 down 兩層的快照能肉眼比對「視野確實差了約半個畫面」，
   這樣我能判斷相對 nudge 有沒有落地到正確角度。
9. 作為 bot 操作者，我想在相對 nudge 的拖曳被吃時照舊跳過該層，這樣不會在角度不明時硬掃。
10. 作為 bot 操作者，我想讓相對 nudge 的每一步都走既有的 `_pitch_drag_verified`（前後幀驗證），
    這樣「拖曳有沒有生效」的判斷與 clamp reset 路徑完全一致、不另立標準。
11. 作為 bot 操作者，我想讓礦坑重置中時不論走哪條路都立刻放棄掃層，這樣不會把時間花在
    已重置的礦坑。
12. 作為 AI agent 維護者，我想讓「當下俯仰 offset」被軟體追蹤，這樣 up→mid→down 的每一步
    nudge 量都從 offset 算出來、不需重錨。
13. 作為 AI agent 維護者，我想讓「從當前 offset 到目標層要 nudge 幾步、各幾 px」是純函式，
    這樣它能被單獨測試、不與 I/O 糾纏。
14. 作為 AI agent 維護者，我想讓開關預設值由實機驗證結果決定，且**翻轉預設只改一個常數**，
    這樣驗過就能安全上線、不動任何邏輯。
15. 作為 AI agent 維護者，我想讓這份 spec 記下「為什麼 +370 直達被否決」「為什麼離線量不到
    nudge 量級」，這樣下一個 session 不會重走同一條死路。

## Implementation Decisions

### D0：先實機驗證，不是先寫碼（gating）

本 spec 的第一個任務是**實機**：在 H065 toggle 修復已上線的前提下，開相對 nudge 開關跑一場
八方位全空的場次，肉眼比對 up／down 層快照的視野是否確實差約半個畫面（≈45°）、且 down 層
看得到 mid 看不到的東西（像 121 那樣）。**驗得過才翻預設；驗不過就讓開關留在 off、本 spec
的碼退居備援。** 沒有這場實機，相對 nudge 不能成為預設。

### D1：新增 config 開關 `sweep_pitch_relative_nudge`，預設 `False`

- `False`（預設）：`_pitch_layer_transition` 逐字回到今日行為——每層 `pitch_reset`＋單次
  nudge。零行為改變、零回歸。
- `True`：跳過 `pitch_reset`，改走相對 nudge（見 D2）。
- 放 AI agent 專屬（不進網頁白名單），與 `sweep_pitch_step_px` 同慣例。
- 翻轉預設只改這一個常數。

### D2：相對 nudge 用 up→mid→down 兩步式，追蹤 offset

- `HarvestState` 新增 `pitch_offset_px: int = 0`——軟體追蹤「當下俯仰距 mid(standard) 的
  nudge 偏移」，單位是 `sweep_pitch_step_px` 的倍數（mid=0、up=−1、down=+1）。
- 新增純函式 `plan_relative_nudges(current_offset: int, target_offset: int) -> list[int]`：
  回傳從當前 offset 到目標 offset 的 nudge 序列，每步固定 ±`step_px`、符號依方向。
  例：`(−1 → +1)` 回 `[+step, +step]`（up→mid→down 兩步）；`(0 → −1)` 回 `[−step]`；
  `(0 → 0)` 回 `[]`。**固定步長、不產生 +370 的單步**——這是「不碰線性」的落點。
- `_pitch_layer_transition` 在開關 on 時：pop 目標層 → `plan_relative_nudges(current, target)`
  → 逐個 nudge 走 `_pitch_drag_verified`（與 clamp reset 路徑同一個驗證）→ 全部生效才更新
  `pitch_offset_px` 與 `pitch_layer`；任一步被吃到兩輪 → 跳過該層（照舊）。
- 礦坑重置中 → 直接回 False（照舊，不拖曳）。
- 層轉換後的重掃 D2（H065 的 `execute_scan` 守門已確保不 toggle 卸裝）照舊在 nudge 之後跑。

### D3：收尾歸位用 offset 反推，不靠 clamp reset

- `_pitch_restore_if_touched` 在開關 on 時：若 `pitch_offset_px != 0`，nudge 回 0
  （`plan_relative_nudges(current, 0)`）；off 時照舊 `_pitch_home_mining`（clamp reset）。
- `pitch_touched` 旗標語意不變（動過就要歸位）；只是歸位手段隨開關分岔。

### D4：up→down 之間過 mid 是短暫過境，不停留

兩步式讓鏡頭在 up→down 之間瞬間經過 mid（standard）。這是過境、不掃描、不影響任何東西。
若實機發現「經過 mid 時畫面變動造成偵測誤觸」，再加 settle——但 121 的 clamp reset 路徑每次
也都經過 mid，沒有此問題，預期不需要。

### D5：開關 off 時，offset 不維護（避免雙真相）

`pitch_offset_px` 只在開關 on 時維護；off 時維持 0（不讀不寫）。兩條路不共享這個欄位的
真相，避免「clamp reset 已歸位但 offset 沒同步」的不一致。

## Testing Decisions

好的測試只驗外部可觀察行為，不驗私有方法、不驗參數逐字內容。

**接縫：一個既有、一個新純函式。**

1. **純函式 `plan_relative_nudges`**（新）：驗「offset→目標」的 nudge 序列正確——
   up→down 是兩步 `[+step,+step]` 不是單步 `[+2*step]`（釘住「不碰線性」這個決策）、
   mid→up 是 `[−step]`、already-at-target 是 `[]`。純函式、無 I/O，比照
   `tests/test_harvester.py` 既有的 `plan_pitch_layers`／`plan_return_rotations` 測法。

2. **`_pitch_layer_transition` 外部行為**（既有接縫）：用 `tests/fake_bot.py` 的
   `make_fake_bot(bind=["_pitch_layer_transition"])` harness（prior art＝
   `tests/test_main_pitch_layer_rescan.py` 的層轉換測試）。鎖住的行為：
   - 開關 on ＋ 目標層 → 觸發 nudge（不走 clamp reset）、nudge 次數＝`plan_relative_nudges`
     的步數、且發生在重掃 D2 之前；`pitch_offset_px` 更新到目標。
   - 開關 off → 行為與今日逐字一致（clamp reset ＋ 單 nudge），作為回歸對照組。
   - 任一 nudge 步兩輪被吃 → 跳過該層、offset 不更新、不觸發重掃。
   - 礦坑重置中 → 回 False、不 nudge。
   - 收尾：開關 on ＋ offset≠0 → nudge 回 0；off → clamp reset。

不為 `sweep_pitch_relative_nudge` 的預設值寫測試（它是要被實機翻轉的常數，釘死只會做改變偵測器）。

## Out of Scope

- **「漂了才 reset」的聰明閘門**（偵測掃描中途俯仰漂移、漂了才 clamp reset）。這是更理想的
  方案，但它的前提「能用 frame-diff 可靠偵測漂移」**離線無法成立**（見 Further Notes），
  需要新的偵測器設計與實機驗證，超出本 spec。本 spec 用「開關＋實機驗證」繞過它：驗得過就
  全用相對 nudge、驗不過就全用 clamp reset，二分乾脆。聰明閘門留作後續 spec。
- **+370 單步直達**（mid→up、up→down 各一次單步 nudge）。被線性假設否決（見 D2／Further Notes）。
- **每輪正常採集都掃三層**。維持失敗路徑限定。
- **改變 `sweep_pitch_step_px` 的值或正負**。校準常數不動。
- **H065 的 toggle 守門**。已 commit，本 spec 假設它已是基線（但仍待實機驗證，見 D0 前置）。
- **掃描中途補 D2**。那是另一個問題（D2 標記壽命 vs 層內掃描時間），不在本 spec。

## Further Notes

### 為什麼 +370 直達被否決（線性死路）

up 後「直接到 down」＝從 up(mid−185) 一次 nudge +370 到 down(mid+185)。這假設 `_drag_vertical`
線性：drag(370) 的效果 = 2 × drag(185)。但 `_drag_vertical` 走 Windows 指標加速曲線
（`pydirectinput.moveRel`，H048 分段），加速曲線對「總位移」非線性——同 chunk 速度下
370 跨越多段加速區、不一定正好是 185 的兩倍。改成兩步 `[+185, +185]`，每步都是同一個已驗證
單位、對稱是構造保證，代價只多一次 nudge（~2s，比 +370 的 ~3s 還接近）。

### 離線量不到 nudge 量級（量測死路，別重走）

試過兩種方法量「pitch_nudge(185) 實際讓畫面移動幾 px、up/down 是否對稱」，**都失敗**：
- **template matching**（中央 strip）：鎖到礦坑重複岩石紋理的錯配，dx 污染 ±83~193、
  分數 0.58~0.72。
- **phase correlation**（FFT，整塊 crop）：全部回 dy≈0（連該大動的 nudge 也是）。

根因：俯仰改變在 3D 礦坑場景是**投影變換**（不同深度位移不同＋透視），不是 2D 平移，
FFT 找不到乾淨位移峰、template 也配不準。bot 自己的 `mean_diff`（121 實測 up-nudge 7.79、
down-nudge 9.00、down-reset-淨185 卻 14.38）混了場景內容、不能當量級代理。

→ **nudge 的一致性／線性只能實機驗**（看 up/down 快照視野差），離線別再試 2D 位移量測。
這也是為什麼 D0 把實機驗證訂為 gating 第一任務。

### clamp reset 可重現是靠構造，不是靠量測

`pitch_reset(1500, 370)`：拖下 1500 必飽和到夾限硬邊界（同一點），回拉 370 是固定拖曳 →
standard 角可重現。這是整個 pitch 系統的前提（「夾限是硬邊界，飽和後回拉多少就是可重現的
絕對角度」），成立。所以 clamp reset 的「絕對歸位」屬性是真的——它不是量測出來的誤差，
是硬邊界構造保證。相對 nudge 沒有這個硬邊界，只能假設「當下＝standard」。

### 121 的數字（基線證據）

clamp reset 實測：mid→up 31s、up→down 44s，共 75s／28%。五次俯仰拖曳的 `mean_diff` 全部
「生效」（沒被吃）。down 層在 dir7/dir0 撈到 Gelisol——功能本身做對了，本 spec 只是把其中
28% 的時間擠掉。

### 前置依賴

- **H065 toggle 守門**（`0736f7c`）必須先實機驗證：若 toggle 沒修好，up 層整層沒掃描，
  相對 nudge 的「up 落地正確與否」無從判讀（up 永遠空）。
- **未 commit 的 sweep-pitch-enable 工作**（`sweep_pitch_step_px=185`、層轉換重掃 D2）
  是本 spec 的基線；它還沒 commit，下一個 session 開工前先確認它已在樹上（或 commit 它）。

### 風險

| 風險 | 對策 |
|---|---|
| 相對 nudge 假設不漂，但窄坑道會漂 | 開關預設 off；實機驗不過就不翻預設 |
| `pitch_offset_px` 軟體追蹤與實際角度分岔（某次 nudge 部分生效） | 每步走 `_pitch_drag_verified`，生效才更新 offset；被吃兩輪跳層 |
| 翻預設後舊場次的 log 判讀混淆（clamp reset vs 相對 nudge） | log 行明標走哪條路 |

### 2026-07-29 追記：121 實機幀改變了任務順序（D0 之前還有一件事）

寫這份 spec 時只用了 121 的**時間數字**（31s/44s/75s），沒有看它的**畫面**。看了之後
（`docs/open-detection-issues.md` D07 有完整幀清單與 log）：

- **up 層八方位全空是幾何必然，不是 D2 toggle**：`step_px=185` 把俯仰抬到讓鏡頭吊臂
  擺進地面，Roblox 把鏡頭拉成貼身特寫，角色身體蓋住候選 ROI 所在的畫面中央。
  查過的 dir0/dir4/dir7 加層尾幀都是這個狀態（＝D05 那個特寫失效族，只是這次是
  bot 自己每次都製造出來）。
- **down 層壓過頭**：全場唯二命中在 y=154／162，畫面最上 15%。
- 五次拖曳 log 全判「生效」，所以**不是被吃**，是落點本身不對。

對本 spec 的影響：

1. **D0 的順位要往後讓一格。** 相對 nudge 與 clamp reset 用的是同一個 `pitch_nudge`
   原語、從同一個標準角出發，換路徑救不了落點。層落點沒校準前跑 02，唯一的結果是
   把「step 校錯」記成「相對 nudge 不成立」。新的第一件事是 issue 00（只改
   `sweep_pitch_step_px`，不動邏輯）。
2. **02 的驗收條目「up 視野抬高約半個畫面」在今天的碼上就過不了**——它現在是
   00 的驗收條目，不是相對 nudge 的。02 剩下的獨有條目只有「沒有 pitch_reset／夾限
   拖曳」「offset 歸 0」「整場少 60-75s」。
3. **Solution 段的省時前提不變**（75s 是真的量到的），但它省的是一個目前落點還錯的
   功能的時間。先校準再省時，順序反過來會把兩個變因綁在同一場。

「離線量不到 nudge 量級」那條仍然成立——這次也不是量出來的，是**肉眼比對三層同方位
的實機幀**判出來的。這正是原本就寫在 spec 裡的判讀方式，只是它可以用**已經存在的
121 幀**做，不必等新的一場。下次要判俯仰落點，先去 MSIX LocalCache 翻
`snapshots/trace/*pitch_ok_{before,after}.png`——每次 `_pitch_drag_verified` 都留了前後全幀。
