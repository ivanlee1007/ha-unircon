# HA Binding Map to Backup Worker Pipeline

Last updated: 2026-04-10

這份文件回答的是：

> `ha-unircon` 已經會存 binding map，怎麼把它和 backup worker 串成真正可跑的一條線？

答案是：

1. 用 HA service 先更新 runtime state
2. 用 HA service 直接存出 binding-map JSON
3. 讓 backup wrapper 吃同一份 JSON 跑 snapshot / diff / Git

---

## 內建 runner

repo 現在提供：

- `tools/run_binding_backup_pipeline.mjs`

它做的事很單純：

1. `unircon.run_health_check`（可選）
2. 等待設備回覆
3. `unircon.save_binding_map`
4. 等待 binding-map 檔案出現
5. 執行 `tools/run_emos_backup_scan.sh`
6. `unircon.sync_backup_status`

也就是：

```text
HA runtime
  -> save binding map
  -> backup worker
  -> sync backup status
  -> Git snapshot history
```

---

## 需要的環境變數

參考：

- `tools/examples/ha-binding-backup.env.example`

最少要有：

```bash
export HA_URL=http://homeassistant.local:8123
export HA_TOKEN=YOUR_LONG_LIVED_TOKEN
export PIPELINE_BINDING_MAP_PATH=/config/unircon/binding-map.generated.json
```

如果你要讓 worker 真正跑起來，通常也會一起帶：

```bash
export EMOS_BACKUP_ROOT=/share/emostore
export EMOS_BACKUP_PUSH=0
```

---

## 最簡單用法

```bash
node tools/run_binding_backup_pipeline.mjs --repo-root /config/ha-unircon
```

如果 repo 就是目前工作目錄，也可以直接：

```bash
npm run backup:pipeline
```

---

## 常用參數

### 指定某幾台 host

```bash
node tools/run_binding_backup_pipeline.mjs \
  --ha-url http://homeassistant.local:8123 \
  --ha-token "$HA_TOKEN" \
  --hosts Relay-685D,sensor01
```

### 跳過 health check

```bash
node tools/run_binding_backup_pipeline.mjs \
  --ha-url http://homeassistant.local:8123 \
  --ha-token "$HA_TOKEN" \
  --skip-health-check true
```

### 跳過最後的 backup status sync

```bash
node tools/run_binding_backup_pipeline.mjs \
  --ha-url http://homeassistant.local:8123 \
  --ha-token "$HA_TOKEN" \
  --skip-backup-status-sync true
```

### 只驗 service，不跑 worker

```bash
node tools/run_binding_backup_pipeline.mjs \
  --ha-url http://homeassistant.local:8123 \
  --ha-token "$HA_TOKEN" \
  --dry-run true
```

---

## 路徑概念

這裡有兩個 path，別混掉。

### 1. `PIPELINE_BINDING_MAP_SERVICE_PATH`

這是傳給 HA `save_binding_map` service 的 path。

預設：

```text
unircon/binding-map.generated.json
```

對 HA 來說，這代表：

```text
/config/unircon/binding-map.generated.json
```

### 2. `PIPELINE_BINDING_MAP_PATH`

這是 host-side runner 真正要拿去餵 worker 的檔案路徑。

預設：

```text
/config/unircon/binding-map.generated.json
```

也就是說，預設設計就是讓兩邊指向同一份檔案。

---

## 建議流程

### 方案 A，手動驗證

先確認 service 路徑通：

1. `npm run backup:pipeline -- --dry-run true`
2. 確認 HA 端沒有 401/404
3. 取消 dry-run 再跑一次
4. 確認：
   - binding map 有落檔
   - worker 有跑
   - repo 有 snapshot / metadata / diff
   - HA 的 backup sensor 有更新

### 方案 B，排程化

等手動通了，再交給：

- cron
- Node-RED exec
- n8n Execute Command

去排程 `npm run backup:pipeline`

---

## 為什麼這條線合理

因為責任切得很乾淨：

### HA / `ha-unircon`
- 知道哪些 host 存在
- 知道 token / runtime state
- 知道 HA device/entity registry
- 負責產出 binding map
- 負責接回最新 backup metadata 狀態

### backup worker
- 掃 backup landing file
- 做 archive / metadata / diff
- 做 Git snapshot

這樣就不會變成：

- worker 反過來猜 HA registry
- 或 HA integration 自己變成 Git engine

---

## 一句話版

> 這個 pipeline runner 是把 `save_binding_map` 和 backup worker 接成一條真正可排程的 HA-host 流程。
