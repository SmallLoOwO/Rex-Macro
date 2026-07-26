# 實機素材庫索引

這裡放**實機截圖／錄音**，用來把偵測邏輯釘在真實畫面上。每個子目錄一份 README
說明該類別的判定、命名與兩側夾（正負樣本各在哪）。

給接手的 AI agent：**先讀本檔選對目錄，再讀該目錄的 README，最後才開圖**。素材是
用來反駁假說的，不是用來確認假說的——調門檻前先把該目錄的負樣本全掃過一遍。

## 硬規則

- **這個目錄有 git 追蹤，`assets/` 沒有。** 測試要用的素材一律放這裡；放 `assets/`
  會被 gitignore 吃掉，別台機器 clone 下來測試就變成 skip。
- **不得為了讓單一 fixture 過就放寬門檻**，也不得刪事故回歸素材（H001~H061）。
  真陽性與負樣本要**兩側夾**：只驗真陽性的門檻等於沒有門檻。
- 檔名帶 `hNNN_` 前綴＝對應 `docs/incidents.md` 的事故編號，該檔就是那次事故的證據。
  沒有前綴的多半是常態語料或對照組。
- CJK 路徑下 `cv2.imread` / `cv2.imwrite` 會**靜默失敗**——讀寫一律走
  `np.fromfile` + `cv2.imdecode` / `cv2.imencode` + `tofile`（既有測試都這樣寫，照抄）。

## 目錄一覽

| 目錄 | 內容 | 主要測試 |
|---|---|---|
| [`aim/`](aim/README.md) | harvest 101 手動瞄準單格限縮偵測（`detect_tracker_core`）＋網頁介入自動收集 | `test_vision.py`、`test_web_server_p5.py` |
| [`boost/`](boost/README.md) | boost 效果列判定（作用中／只剩次數） | `test_boost_fixtures.py` |
| [`boost_count/`](boost_count/README.md) | 右下角 boost 使用次數紅字 OCR（內嵌數字模板） | `test_vision.py` |
| [`capacity/`](capacity/README.md) | 背包容量百分比 OCR（含 101% 溢位） | `test_capacity_fixtures.py` |
| [`chat/`](chat/README.md) | 聊天框 OCR 與採集確認信號（H005/H010/H014/H020/H039/H041） | `test_ocr_fixtures.py`、`test_harvester.py` |
| [`chat_icon/`](chat_icon/README.md) | 聊天圖示開／關外觀判定（H047） | `test_chat_icon.py` |
| [`chat_ui/`](chat_ui/README.md) | **已退役**——舊的輸入列提示字 OCR 路徑（被 H047 取代） | 無 |
| [`chill/`](chill/README.md) | chill 音訊參考與負樣本（H040/H060） | `test_add_chill_ref.py` |
| [`effect_row/`](effect_row/README.md) | D2 雷達效果列判讀（Local／CaveSkim／D4 已用） | `test_effect_row_fixtures.py` |
| [`menu/`](menu/README.md) | Roblox 設定選單 Movement Mode 循環 | `test_roblox_menu.py` |
| [`pitch/`](pitch/README.md) | 俯仰動作「真的動了」vs「被吃」兩側夾（H048/H052） | `test_pitch_fixtures.py` |
| [`player_list/`](player_list/README.md) | 右上角玩家列表開／關 | `test_player_list_fixtures.py` |
| [`reentry/`](reentry/README.md) | 回礦：Depth 錨、開場凍結、放大圖漂移（H044/H046/H050） | `test_reentry_fixtures.py`、`test_depth_fixtures.py` |
| [`slot/`](slot/README.md) | 快捷列裝備／未裝備色差 | `test_slot_fixtures.py` |
| [`tracker/`](tracker/README.md) | 追蹤框偵測的同色黏連救援（H057） | `test_vision.py` |

## 命名規則

```
h047_icon_closed_hollow.png          事故素材：h<事故編號>_<情境>_<判定>
101_core_green_b1.png                harvest 編號素材：<harvest_id>_<用途>_<色系>_<格>
count_124.png / none_sky.png         值素材：<欄位>_<真值> / none_<否定情境>
eaten_reset_before.png / _after.png  前後對比：<情境>_before / _after 必須成對
auto_007_success.png + .json         網頁介入自動收集（見 aim/README.md）
```

⚠ `harvest_id`（101、007）是**流水號不是事故碼**，跟 `Hxxx` 不同系統，別混。

## 加新素材前

1. 這是**實機**畫面嗎？合成圖只能驗演算法、驗不了「會不會對地形開火」。
2. 有沒有配套的**負樣本**？只加真陽性會讓門檻單邊漂移。
3. 放對目錄了嗎？放 `assets/` 會被 gitignore。
4. 更新該目錄的 README 表格——這份索引是給看不到圖的人用的，漏更新等於沒加。
