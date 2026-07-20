# 回礦 yaw 調查：07-20 設計文件根因否證與語料重定位

- 日期：2026-07-21
- 狀態：**調查報告（否證前案；新根因未定）**
- 修正對象：`docs/superpowers/specs/2026-07-20-reentry-yaw-reroll-random-design.md`
- 相關 commit：`b9f7783`（回礦收尾補 yaw 回正）、`5f500b6`（被本文否證的設計文件）
- 對應事故：H059（根因待定，暫不寫入 `docs/incidents.md`）

## 摘要

07-20 設計文件把 b9f7783 失效歸因於「reroll 隨機化 yaw」，並據此提出視覺
校正方案，同時宣告「作者為純文字模型、無法評估」而擱置。本輪查核推翻其中
兩項前提：

1. **作者可讀圖**——「需有視覺能力者執行」的路障不存在。
2. **ep10／ep11 從未 reroll**——ledger 直接證明，該文件的根因鏈失效。

視覺校正的語料同時被重新定位：它一直存在，只是文件指錯路徑、也誤判了檔案
內容。**新的根因未知**，b9f7783 為何失效仍待查。

## 一、否證：ep10／ep11 從未 reroll

07-20 文件「證據 2」寫：

> 實機 `harvest.log`（07-20 RR#10／RR#11，皆 attempt 4＝reroll 過）

`attempt` 不是 reroll 次數。ledger 每個 episode 的 `log` 陣列會逐筆記錄指令
與 `kind`，reroll 有專屬 `kind: "reroll"`。可重現查核：

```bash
uv run python -c "
import json
p = '<log_dir>/reentry_remote/ledger.jsonl'
for line in open(p, encoding='utf-8'):
    if not line.strip(): continue
    e = json.loads(line)
    kinds = [c.get('kind') for c in e.get('log', [])]
    print(e['episode'], e.get('attempt'), kinds.count('reroll'), kinds)
"
```

實測輸出：

| ep | attempt | reroll 次數 | 指令序列 |
|---|---|---|---|
| 3 | 4 | **0** | pitch_reset,pitch×3,sweep,pitch_save,fine,coarse×2,magnify,fine,confirm |
| 4 | 4 | **0** | layer,coarse,magnify,fine×3,confirm |
| 5 | 4 | **0** | coarse,magnify,fine,confirm |
| 9 | 4 | **0** | coarse×2,sweep,coarse,layer,magnify,fine,confirm |
| **10** | **4** | **0** | coarse,magnify,back,magnify,layer,fine×2,confirm |
| **11** | **4** | **0** | coarse,magnify,fine,confirm |
| 12 | 5 | **1** | **reroll**,coarse,magnify,fine,confirm |
| 1 | 11 | 1 | reroll,skip |

ep12 有 `reroll` 而 ep10／ep11 沒有，證明**該欄位在 reroll 發生時確實會記**，
ep10／ep11 的空白是真的沒發生，不是漏記。attempt=4 出現在 ep3/4/5/9/10/11，
reroll 全為 0——`attempt` 與 reroll 完全不相關。

交叉佐證：全部 log 中 `RemoteReply(kind='reroll')` 一生只出現 5 次
（07-17 17:26、07-19 03:40、07-19 19:34、07-20 02:46、07-20 21:22）。
ep10 時窗約 19:36–19:47、ep11 約 20:22–20:28，兩者都不含任何一次；
07-20 21:22 那次對應 ep12。reroll 是**使用者手動指令**（文字或 🎲 reaction），
不會自動發生。

### 後果

07-20 文件的「根因一句話」、證據 2、證據 3、以及那張「轉與不轉都 ~50%」的
機率表，全部建立在「ep10／ep11 reroll 過」之上，**均不成立**。

在沒有 reroll 的前提下：基底 yaw 沒有被遊戲隨機化，`ctx.cur_dir` 記帳與
`restore_view` 的旋轉次數又都經該文件驗證為正確——**b9f7783 理應生效，但
使用者仍觀察到對角。真正的失效機制目前未知。**

## 二、語料重定位

07-20 文件指的素材路徑是錯的，且誤判了關鍵檔案的內容。

### 路徑

文件寫 `logs/snapshots/review/sweep_empty_dir*.png`。repo 內該目錄有 58 個檔，
**沒有任何 sweep 檔**。實際位置是 MSIX 重導路徑（見 `CLAUDE.md` 實機排錯段）：

```
%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\
  LocalCache\Local\RexMacro\logs\snapshots\
```

`review/` 內有 220 檔，含 **14 輪完整八方位** sweep（round 084–100），檔名格式
`<日期>_<時間>_<奈秒>_<序號>_<round>_sweep_empty_dir<N>.png`。

### `*_landing.png` 是礦層內幀，不是地表

`snapshots/reentry/` 有 11 張 `ep{N}_click{M}_landing.png`。這批是
**視覺校正真正要吃的幀**——傳送落地後的礦層畫面。判讀依據：HUD 顯示
`Depth: 7100m`、`Mine Capacity: 0%`，且畫面右下有「Go to surface」按鈕
（＝人在礦內）。對照挖礦中的 sweep 幀為 `Depth 7406m/Capacity 36%`、
`Depth 7665m/Capacity 88%`，可見 Depth 隨挖礦推進變化，7100m + 0% 就是
Shamrock 層剛進場、尚未開挖的狀態。

**結論：語料一直存在。07-20 文件「無素材可評估」的處境是路徑錯誤造成的。**

## 三、視覺訊號現況（初評，未定案）

已看過：sweep round 084/085/087/090/096/100 的八方位、round 084–100 的 dir0
橫向對照、11 張礦層 landing 幀、ep10 地表八方位掃描。

**有利：**

- 礦層地形是**平面盒狀、直線邊、直角**（round 100 dir0/dir4 最清楚：走道牆面
  為連續平面，消失點結構完整）。07-20 文件候選訊號 1（邊緣方向直方圖）有實體
  基礎。

**不利／需繞開：**

- 掃描幀中唯一穩定的強結構是 **dir0／dir4 開闊、其餘 6 向鏡頭卡住**。但 dir0
  依定義就是當前面向，而那條走道是 **bot 自己用 W 挖出來的坑道**，走向＝bot
  當時朝向。此訊號**自指**，不含世界軸資訊，不能當絕對 yaw 參考。
- HUD **沒有 compass／小地圖**，07-20 文件候選訊號 3 出局。
- 約 6/8 的掃描幀是鏡頭穿進地形或貼在角色身上的特寫，可用率低。這批是
  「八方位全空才存」的最壞情況取樣，對 landing 幀不必然適用。

**尚缺：** 沒有任何一張**確認為「斜挖」的負樣本**。所有看得清楚的坑道都像沿軸。
沒有負樣本就無法依 `AGENTS.md`／H040／H054 慣例做門檻兩側夾，因此
**現階段不能寫分類器門檻**——只能寫骨架，參數待標註語料到位。

## 四、本輪自我修正紀錄

以下三項是調查過程中先下、後被自己推翻的判斷，列出以免再犯：

| 曾判斷 | 實際 | 推翻依據 |
|---|---|---|
| 礦層是 Roblox 有機平滑地形、無方格 | 是平面盒狀、直線邊直角 | 放大 round 100 dir0/dir4；先前看到的「不規則鋸齒團塊」是鏡頭穿進 geometry 的剪裁 silhouette |
| 11 張 landing 幀視覺上完全相同 | **未成立** | 背景 ROI 兩兩平均絕對差 5.4–16.4，暗綠雜訊紋理上不具鑑別力，證不了同也證不了異 |
| 「LIMIT」看板同位置 ⇒ 相機沒轉、`cur_dir` 記帳脫節 | **錯** | ep10 地表八方位掃描中 LIMIT 與層名牌位置完全不動、背景整個換掉 ⇒ 兩者都是螢幕空間 UI，不能當世界物件用 |

第三項一度導出「b9f7783 反而製造對角」的推論，該推論**連同其前提一併作廢**。

## 五、已確認的遊戲事實（使用者回答）

- 礦層落地時周圍是**實心岩**，要自己挖；沒有現成坑道網。
- **直角與對角對挖礦效率有影響**，這是使用者的實際痛點（非觀感問題）。

「實心岩」意味著 landing 當下沒有坑道可對齊，任何「對齊到現成通道」的做法
在該時間點無效；訊號必須來自礦體本身的結構（方塊面／礦脈走向）。

## 六、待辦

1. **重查 b9f7783 失效機制**——在無 reroll、記帳正確、旋轉次數正確的前提下，
   為何仍對角。這是目前最大的未知，優先於任何視覺實作。
2. **取得負樣本**——標註「沿軸」與「斜向」的礦層幀各若干，才可能做兩側夾。
3. **釐清症狀分佈**——對角是每次必然、還是約一半？決定根因是確定性偏移還是
   隨機性，兩者修法完全不同。
4. 過渡項（與上述獨立、可先做）：`main.py:4951-4954` 的註解本身**未被本文
   否證**——它只描述症狀與 `restore_view` 的機制，沒有引用 reroll。被否證的是
   07-20 設計文件對 b9f7783 失效原因的解釋。但既然已知 `restore_view` 實際上
   沒有消除症狀，該處值得補一行「本呼叫已知不足以消除對角，根因調查見
   2026-07-21 findings」，避免後人誤以為此路已修好。

   注意：`b9f7783` commit message 主張的「teleport 保留 yaw（實機確認）」
   本輪**既未證實也未推翻**，不可當已否證處理。

## 限制聲明

本文只否證前案並重定位語料，**不提出新根因**。第一節的否證有 ledger 直接
證據，可重現；第三節的視覺初評是觀察，未經量測兩側夾，不得直接當門檻依據。
