# START HERE｜給 Steven 的啟動說明

這包是把 v2 研究報告和 Master Build Prompt 轉成 Claude Code 可以直接執行的專案骨架。內容包含常駐規則、規格勘誤、技術決策，以及 Phase 0 的逐步任務與驗收標準。解壓縮後放進 repo 根目錄，Claude Code 會自動讀取 `CLAUDE.md`，再依照 `docs/` 一步步開發。

## 檔案地圖

| 檔案 | 給誰看 | 用途 |
|---|---|---|
| `START_HERE.md` | 你 | 這份啟動說明 |
| `CLAUDE.md` | Claude Code | 每次 session 自動載入的常駐規則：禁止事項、工作流程、技術基線 |
| `docs/STATUS.md` | 兩者 | 目前進度；每次 session 開始讀、結束更新 |
| `docs/spec/SPEC_ERRATA_v2.1.md` | Claude Code | v2 兩份文件的衝突與缺口裁決，優先於原始規格 |
| `docs/decisions/DECISIONS.md` | 兩者 | 技術決策（ADR）與待你決定的事項（OD） |
| `docs/milestones/M0_foundation.md` | Claude Code | Phase 0 拆成 M0.1–M0.10，每步都有驗收清單 |
| `docs/milestones/ROADMAP.md` | 兩者 | Phase 1–6 的進場條件與出場標準 |
| `docs/glossary/glossary_seed.yaml` | Claude Code | 小問號 tooltip 的詞彙表種子（39 個詞） |
| `docs/spec/01_…v2.md`、`02_…v2.md` | Claude Code | 你的 v2 原始規格（轉成 Markdown，需要時查閱） |
| `config/universe.yaml` | 你 | Phase 0 測試用股票清單，可自行增減 |
| `.env.example`、`.gitignore`、`.claude/settings.json` | 系統 | 金鑰欄位範本、Git 忽略規則、禁止 Claude Code 讀取 `.env` |

## 啟動步驟

1. **安裝工具**：Docker Desktop、Git、Claude Code 桌面版。
2. **把資料夾直接當成 repo**：解壓縮後會得到 `autotrading/` 資料夾，整個資料夾就是 repo 根目錄。裡面有 Finder 預設看不到的隱藏檔（`.claude/`、`.gitignore`、`.env.example`），所以不要只拖曳看得到的檔案到別處。之後用 GitHub Desktop 的「Add Local Repository」推到 private repo，或請 Claude Code 幫你執行 `git init` 與第一次 commit。
3. **準備金鑰**（Phase 0 只需要三樣）：
   - SEC：不用申請，只要一串「你的名字 + email」當 User-Agent。
   - FRED：到 FRED 網站申請免費 API key。
   - Alpaca：開 paper 帳戶取得 Market Data key（Basic 免費方案）。開戶時順便確認新加坡居民是否可申請（OD-9）。
4. **自己建立 `.env`**：在 terminal 執行 `cp .env.example .env`，用文字編輯器填入金鑰。不要請 Claude Code 代填或讀取這個檔案。
5. **用 Claude Code 桌面版打開 repo 資料夾**，貼上下面的第一句指令。

## 第一句指令（直接複製）

```
請先讀 CLAUDE.md、docs/STATUS.md、docs/spec/SPEC_ERRATA_v2.1.md、docs/decisions/DECISIONS.md 和 docs/milestones/M0_foundation.md。完整規格在 docs/spec/，需要時再查。

用 plan mode 規劃 M0.1（Repo scaffold and local stack）：列出要建立的檔案、docker compose 服務、Makefile targets、CI 流程與測試，以及你看到的風險或規格衝突。先不要寫任何程式碼，等我確認計畫。
```

## 之後每一步的節奏

1. Claude Code 在 plan mode 提出計畫，你確認後才實作。
2. 實作完成後，它要交出 Build Output Contract：完成狀態、檔案變更、測試結果、驗收清單、已知缺口。
3. 你檢查驗收清單後 merge，再下指令：

```
M0.x 已合併。請更新 docs/STATUS.md，然後用 plan mode 規劃下一個 sub-milestone。
```

4. 每完成 2–3 個 sub-milestone，或遇到它說「規格衝突、需要你決定」時，把它的報告貼回這個 Chat Project，做架構審查與規格修訂。

## 需要你決定的事

| 編號 | 決定事項 | 期限 |
|---|---|---|
| OD-9 | 確認 IBKR 是否接受新加坡居民開戶（Alpaca 部分已於 2026-10-06 確認） | Phase 5 |
| OD-2 | 告警要推播到哪裡（Email／Telegram／Slack） | Phase 1 |
| OD-3 | 分析師共識預估的資料來源（S2 財報策略需要） | Phase 1 |
| OD-7 | 含已下市股票的歷史資料來源（回測必需） | Phase 2 |

其餘項目（OD-4、5、6、8）列在 `DECISIONS.md`，到對應 Phase 再決定即可。

## 安全提醒

- `.claude/settings.json` 只能阻擋 Claude Code 用內建工具讀 `.env`，擋不住 shell 指令。所以 `CLAUDE.md` 另外規定禁止用 shell 讀取，最可靠的防線仍然是 Phase 5 之前 `.env` 裡完全不放券商金鑰。
- 任何要付費的方案（例如 Massive $199/月），Claude Code 都必須先停下來問你。Phase 0 用免費資料源就能完成。
- 看到 `DEMO DATA` 橫幅或 `Data unavailable`，代表系統照規則運作，不是壞掉了。
