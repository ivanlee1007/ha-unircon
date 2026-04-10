# EMOS Git Backup Automation on HA Host

Last updated: 2026-04-10

這份文件回答的是：

> worker 已經有了，怎麼在 HA 同機器上穩定跑起來？

重點不是做超華麗編排，而是先做 **穩、可追、容易除錯**。

---

## 建議策略

我建議分兩層：

1. **核心工作**
   - 用 `tools/emos_backup_worker.mjs`
   - 負責 snapshot / metadata / diff / Git commit

2. **排程或編排**
   - 用 `tools/run_emos_backup_scan.sh`
   - 再由 cron / Node-RED / n8n 來叫它

這樣的好處是：

- 核心邏輯集中
- 外圍排程可替換
- Node-RED / n8n 不需要承擔狀態機

---

## 新增 wrapper

repo 內建：

- `tools/run_emos_backup_scan.sh`

功能：

- 建 lock，避免重複執行
- 呼叫 worker
- 可讀 env 設定
- 可選擇自動 push Git remote

---

## env 設定範例

參考：

- `tools/examples/emos-backup.env.example`

最小可用例：

```bash
export EMOS_BACKUP_ROOT=/share/emostore
export EMOS_BACKUP_PUSH=0
bash tools/run_emos_backup_scan.sh
```

若要帶 host map：

```bash
export EMOS_BACKUP_HOST_MAP=/config/ha-unircon/host-map.json
bash tools/run_emos_backup_scan.sh
```

若要自動 push：

```bash
export EMOS_BACKUP_PUSH=1
export EMOS_BACKUP_GIT_REMOTE=origin
export EMOS_BACKUP_GIT_BRANCH=main
bash tools/run_emos_backup_scan.sh
```

---

## 方案 A：cron / shell 排程

最適合先上線。

### 範例 crontab

每 5 分鐘掃一次：

```cron
*/5 * * * * cd /config/ha-unircon && . /config/ha-unircon/.env.backup && bash tools/run_emos_backup_scan.sh >> /config/ha-unircon/logs/backup-scan.log 2>&1
```

### 建議目錄

```text
/config/ha-unircon/
  .env.backup
  host-map.json
  logs/
```

### 優點

- 最簡單
- 最好除錯
- 沒有多餘平台耦合

### 缺點

- UI 比較弱
- 通知要自己補

---

## 方案 B：Node-RED

如果你想要視覺化排程和通知，Node-RED 很適合拿來當 **外圍編排層**。

### 建議 flow

1. `inject` node
   - 每 5 分鐘觸發
2. `exec` node
   - 執行 wrapper
3. `switch` node
   - 判斷 exit code
4. `debug` / `call-service` node
   - 成功時記錄 logbook 或 event
   - 失敗時發 notification

### exec command 範例

```bash
cd /config/ha-unircon && . ./.env.backup && bash tools/run_emos_backup_scan.sh
```

### Node-RED 適合拿來做

- 排程
- 失敗通知
- 成功後丟 HA event
- 成功後送 Telegram / LINE

### 不要把什麼塞進 Node-RED

- normalization 規則
- diff classification 核心
- Git snapshot 邏輯
- restore gate

這些還是留在 worker 內。

---

## 方案 C：n8n

n8n 也能做，但我會把它定位成：

- 跨系統通知
- webhook / issue / chatops 串接

### Execute Command 範例

```bash
cd /config/ha-unircon && . ./.env.backup && bash tools/run_emos_backup_scan.sh
```

### 適合的後續動作

- 讀取 worker JSON output
- 建 issue
- 發 Slack / Telegram
- 寫外部 audit DB

### 不建議

不要讓 n8n 變成真正 backup engine。

---

## host-map 建議

若要讓 metadata 好看一些，可以提供：

- `tools/examples/host-map.sample.json`

例如：

```json
{
  "7432284": "Relay-685D"
}
```

未來這份 mapping 可以再升級成：

- serial -> host
- host -> HA device_id
- host -> entity ids

但第一版先不要做太重。

---

## lock 機制

wrapper 目前會建立：

```text
/share/emostore/runtime/scan.lock
```

若上一次執行還沒結束，下一次會直接 skip。

這是為了避免：

- cron 重疊
- Node-RED 重複點火
- Git repo 被同時寫入

---

## push 建議

### 建議預設

先：

```bash
EMOS_BACKUP_PUSH=0
```

等本地驗證穩了，再打開 push。

### 原因

因為 backup 內容可能包含敏感資訊：

- Wi-Fi 密碼
- MQTT 帳密
- admin 密碼

所以 remote 一定要是 **private Git repo**。

---

## 我推薦的上線順序

### 第 1 階段

- FTP 收件成功
- 手動跑 wrapper
- 看 archive / diff / metadata 是否正確

### 第 2 階段

- 用 cron 或 Node-RED 定時執行
- push 先關掉

### 第 3 階段

- 加失敗通知
- 加成功摘要
- 視情況再開 Git push

---

## 最推薦組合

如果你現在要快、穩、容易維護，我推薦：

- **worker**：`tools/emos_backup_worker.mjs`
- **wrapper**：`tools/run_emos_backup_scan.sh`
- **scheduler**：cron 或 Node-RED
- **storage**：HA 同機 FTP + private Git repo

---

## 一句話版

> **把狀態邏輯留在 worker，把排程與通知交給外圍工具。**

這樣最不容易失控。
