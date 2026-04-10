# Git Backup Runbook for EMOS on Home Assistant Host

Last updated: 2026-04-10

## 目的

這份文件不是講概念，而是講 **怎麼先做一版能用的 Git 簡版備份版控**。

目標是先完成：

- EMOS 備份檔落地到 HA 同機器
- 保留歷史版本
- 可看 diff
- 可追蹤每次變更

先不要急著做完整 rollback engine。

---

## 適用範圍

適用於這種場景：

- Home Assistant 主機可安裝 add-on / Docker 應用程式
- EMOS 裝置用 FTP 將 backup 丟到 HA 同機器
- 你想先用最小成本做版本控制

---

## 最小前置需求

### HA 同機建議至少具備

1. **Mosquitto broker**
   - 給 `ha-unircon` 使用

2. **FTP server**
   - 給 EMOS backup upload 使用

3. **Terminal & SSH** 或 **Advanced SSH & Web Terminal**
   - 需要 Git、shell、基本檔案操作能力

4. **Filebrowser** 或其他檔案查看工具
   - 方便人工檢查 archive 結果

### 可選但很有幫助

- **Node-RED**
- **n8n**
- **Samba**

如果你不想自己長駐 shell watcher，用 Node-RED / n8n 排程掃描也可以。

---

## 建議目錄

建議把資料放在 HA 容易存取、也容易備份的位置。

### 建議路徑

```text
/share/
  7432284.txt
  1234567.txt

/share/emostore/
  latest/
  repo/
    archive/
    metadata/
    normalized/
    diffs/
```

### 各資料夾用途

- `/share/*.txt`
  - FTP server landing path
  - EMOS 直接上傳到這裡
  - 可能會被同名覆蓋

- `latest/`
  - 每台設備目前最新一份 backup

- `archive/`
  - 每次收件後存不可變 timestamp snapshot

- `metadata/`
  - 每份 snapshot 的 JSON metadata

- `normalized/`
  - 給 diff 用的正規化文本

- `diffs/`
  - previous/current 差異摘要

- `repo/`
  - Git repository root

---

## 建議檔名規則

### Landing file

EMOS 常見是固定檔名，例如：

```text
/share/7432284.txt
```

### Archive snapshot

改存成：

```text
/share/emostore/repo/archive/7432284/2026-04-10T16-43-00+08-00.txt
```

### Metadata

```text
/share/emostore/repo/metadata/7432284/2026-04-10T16-43-00+08-00.json
```

### Normalized

```text
/share/emostore/repo/normalized/7432284/2026-04-10T16-43-00+08-00.norm.txt
```

### Diff summary

```text
/share/emostore/repo/diffs/7432284/2026-04-10T16-43-00+08-00.diff.md
```

---

## Git repo 建議結構

`repo/` 內建議只放真正要版控的內容：

```text
repo/
  archive/
    7432284/
  metadata/
    7432284/
  normalized/
    7432284/
  diffs/
    7432284/
```

### 為什麼不把 inbox 也放進 Git

因為 `/share/*.txt` 是 landing zone，容易反覆覆蓋，不適合當歷史來源。

---

## 驗收口徑

第一版 backup pipeline 的驗收，建議拆成三層判讀：

### 1. Integration / identity 層
- `run_health_check` / `request_token` 能把 runtime state 拉起來
- `save_binding_map` 能正確落出 serial -> host / HA device 對應

### 2. Ingestion / worker 層
- HA 主機上真的有 `/share/<serial>.txt`
- worker 能吃進 archive / metadata / diff
- `sync_backup_status` 能把結果匯回 HA

### 3. Device capability 層
- 這台 firmware 是否真的支援，且已知 manual backup trigger 語法
- 若 device-side capability 未明，就不要直接把缺檔算成 worker bug

### 建議驗收表達

- 全數閉環：`5/5 synced`
- 若只剩已知舊韌體例外：`4/5 synced + 1 waived legacy exception`

### 已知例外

- `USS-P130_f5`
- firmware: `3.62.p5(M-H)T.w3.s8 adv`
- binding map 正常
- token / runtime state 正常
- manual backup trigger 語法未壓實
- `/share/7868660.txt` 缺席時，應先判成 **legacy firmware exception**

---

## 建議第一版流程

### Step 1. EMOS 上傳到 FTP landing path

例如：

```text
/share/7432284.txt
```

### Step 2. watcher / scanner 發現檔案變化

第一版不一定要做即時 watcher。

最簡單可行做法：

- 每 1 到 5 分鐘掃一次 `/share/*.txt`
- 比對檔案 mtime / size / sha256

### Step 3. 產生 snapshot

對新檔案：

- copy 到 `latest/<serial>.txt`
- copy 到 `archive/<serial>/<timestamp>.txt`
- 計算 sha256
- 建 metadata JSON

### Step 4. 產生 normalized view

先做最簡版就好：

- 去掉空白尾巴
- 統一換行
- 規則化排序（如果格式允許）

### Step 5. 比對上一版

如果該 serial 已有上一份 snapshot：

- diff previous vs current normalized file
- 寫成 markdown summary

### Step 6. commit 到 Git

把以下檔案 commit 進去：

- archive snapshot
- metadata JSON
- normalized file
- diff summary

---

## Metadata 最小欄位

第一版 JSON 至少要有：

```json
{
  "serial": "7432284",
  "host": "Relay-685D",
  "received_at": "2026-04-10T16:43:00+08:00",
  "source_path": "/share/7432284.txt",
  "archive_path": "archive/7432284/2026-04-10T16-43-00+08-00.txt",
  "normalized_path": "normalized/7432284/2026-04-10T16-43-00+08-00.norm.txt",
  "size": 3472,
  "sha256": "...",
  "previous_sha256": "...",
  "changed": false,
  "change_type": "identical",
  "ha_device_id": null,
  "notes": "initial simple pipeline"
}
```

---

## Git commit 規則

### 建議 commit message

```text
backup(7432284): snapshot 2026-04-10T16:43:00+08:00
```

如果想再清楚一點，可加第二行：

```text
host: Relay-685D
change: identical
```

### 建議分類

`change_type` 可先用這幾種：

- `initial`
- `identical`
- `network_changed`
- `credentials_changed`
- `deploy_changed`
- `control_changed`
- `unknown_changed`

第一版分類不用太聰明，先有就好。

---

## 第一版不要做太複雜的事

### 不建議一開始就做

- 自動 restore
- 自動 rollback
- 太細的 parser
- 強依賴資料庫
- 跨多站台的複雜策略

### 第一版最重要的是

- raw file 保住
- 每次來檔都能存歷史
- 能查前後差異
- Git log 可追

---

## Watcher 實作方式建議

### 方案 A, shell script + cron / 定時器

適合：
- 先求簡單
- 單機
- 量不大

### 方案 B, Node-RED

適合：
- 想用視覺化流程
- 想順便做通知
- 想把 diff 結果送到 HA event / Telegram / LINE

### 方案 C, n8n

適合：
- 想把檔案事件、Git、通知、Webhook 串在一起

### 我的建議

如果是你現在這階段，**先用 shell / Node-RED 就夠了**。
不要一開始就做太重。

---

## 與 `ha-unircon` 的關係

`ha-unircon` 在第一版不需要直接接管整條 pipeline。

它比較適合先做：

- 顯示 latest snapshot time
- 顯示 latest snapshot hash
- 顯示 last backup result
- 顯示是否與上一版相同
- 觸發 backup / compare / inventory export

也就是說：

- **Git pipeline = 真正版本控制核心**
- **ha-unircon = 操作入口與可視化層**

---

## `.gitignore` 建議

若 `repo/` 是純 backup repo，通常不需要忽略 archive。

但可以忽略：

```gitignore
# temp files
*.tmp
*.swp

# editor noise
.DS_Store
Thumbs.db

# optional runtime scratch
runtime/
```

### 不要忽略

- `archive/`
- `metadata/`
- `normalized/`
- `diffs/`

不然就失去版本控制意義了。

---

## 權限與安全

這個點很重要。

EMOS config backup 很可能含：

- Wi-Fi SSID / password
- MQTT 帳密
- admin 帳密

所以這個 Git repo 應視為：

- **private repository**
- **ops-only access**
- **不能公開**

### 建議

- Git remote 用 private repo
- 不要丟 public GitHub
- Samba / Filebrowser 也要有限制

---

## 第一版驗收標準

做到以下就算過關：

1. EMOS 成功上傳 backup 到 HA 同機 FTP
2. pipeline 會產生 timestamp archive
3. Git 會新增 commit
4. 可以看到前後 diff
5. 原始 raw backup 沒被覆蓋掉

---

## 建議下一步

做完這個 runbook 後，下一步最值得補的是兩個：

1. **snapshot metadata schema**
   - 讓 `ha-unircon` 未來能接進來

2. **binding model**
   - 把 serial / host 對到 HA device registry

---

## 一句話總結

如果你要先做簡版，正確姿勢是：

> **FTP 收件，Git 留史，diff 看變更，`ha-unircon` 做入口。**

先做到這樣，就已經很有用了。
