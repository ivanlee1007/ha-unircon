# EMOS Git Backup Worker

Last updated: 2026-04-10

`tools/emos_backup_worker.mjs` 是這個 repo 目前的 **starter worker**。

如果你要的是「可直接排程的入口」，搭配：

- `tools/run_emos_backup_scan.sh`
- `tools/run_binding_backup_pipeline.mjs`

定位很明確：

- 掃描 FTP landing inbox
- 把 backup 轉成 archive snapshot
- 生成 normalized / diff / metadata
- 選擇性 commit 到 Git

它不是完整 restore engine，也不是長駐 daemon。

---

## 功能

目前這版會做：

1. 掃描 EMOS FTP landing dir 的 `*.txt`（預設 `/share/<serial>.txt`）
2. 用檔名推 serial（例如 `7432284.txt`）
3. 建立：
   - `latest/<serial>.txt`
   - `repo/archive/<serial>/<timestamp>.txt`
   - `repo/normalized/<serial>/<timestamp>.norm.txt`
   - `repo/diffs/<serial>/<timestamp>.diff.md`
   - `repo/metadata/<serial>/<timestamp>.json`
4. 維護 `runtime/worker-state.json`
   - 避免同一份 inbox 檔在下一輪掃描被重複吃進去
5. 可選擇自動 Git commit
6. 可讀 binding map，把 serial 對到 host / HA device / base entities

---

## 預設路徑

若不帶參數，預設：

- inbox: `/share`
- root: `/share/emostore`
- repo: `/share/emostore/repo`

也就是：

```text
/share/
  7432284.txt
  1234567.txt

/share/emostore/
  latest/
  runtime/
  repo/
    archive/
    metadata/
    normalized/
    diffs/
```

---

## 用法

### 只掃一次，不 commit

```bash
node tools/emos_backup_worker.mjs --root /share/emostore --inbox /share
```

### 掃一次並 commit

```bash
node tools/emos_backup_worker.mjs --root /share/emostore --inbox /share --commit
```

### 用 package script

```bash
npm run backup:scan -- --root /share/emostore --inbox /share --commit
```

### Dry run

```bash
node tools/emos_backup_worker.mjs --root /share/emostore --inbox /share --dry-run
```

---

## 可選參數

- `--root <path>`
  - backup working root
- `--inbox <path>`
  - EMOS FTP landing dir, 預設 `/share`
- `--repo <path>`
  - Git repo root, 預設是 `<root>/repo`
- `--host-map <path>`
  - 舊格式相容參數，JSON 檔提供 serial -> host 對應
- `--binding-map <path>`
  - 新格式 binding map，提供 serial -> host / HA device / base entities 對應
- `--commit`
  - 掃描後自動 Git commit
- `--dry-run`
  - 不落檔，只輸出結果

---

## binding map

推薦看：

- `docs/git-backup-binding-map.md`
- `tools/examples/binding-map.sample.json`

最簡版仍可用舊格式：

```json
{
  "7432284": "Relay-685D",
  "1234567": "USS-P130_f5"
}
```

若用新格式，metadata 會多帶：

- `site`
- `ha_device_id`
- `mqtt_identifier`
- `base_entities`
- `device_identity`

這樣後面做 HA overlay 才接得起來。

---

## state file 作用

`runtime/worker-state.json` 會記錄：

- inbox path
- mtime
- size
- sha256
- last processed time

目的是避免 scanner 每次執行都把同一份 landing file 再吃一次。

這很重要，否則只要 inbox 檔沒被覆蓋，排程每跑一次就會多一份假歷史。

---

## 輸出 JSON

worker 執行完會輸出 JSON summary，方便：

- shell script 接
- Node-RED 接
- n8n 接
- 之後接回 HA event
- 之後接回 HA backup status sensor

---

## Git 行為

若加 `--commit`：

- 若 repo 不存在 `.git`，會先 `git init`
- 自動 `git add .`
- 若有變更，會 commit

commit message 形式：

```text
backup(7432284): snapshot 2026-04-10T17:02:00+08:00
```

第二段 message 會帶：

- host
- change type

---

## 目前限制

這是 starter worker，目前故意收斂，不做太多：

- 沒有長駐 watch mode
- 沒有 restore workflow
- 沒有真正語意 parser
- `change_type` 目前是 heuristic
- 還沒直接回寫 HA / `ha-unircon`
- **不能替設備補出不存在的 landing file**，也就是說，如果某台舊韌體設備根本還沒有成功把 backup 丟到 `/share/<serial>.txt`，worker 不會也不該把它包裝成 synced

這是刻意的，先把第一版做穩。

### 已知 legacy exception

截至 2026-04-10，`USS-P130_f5`（`3.62.p5(M-H)T.w3.s8 adv`）已確認：

- binding map 正常
- runtime token 正常
- 但 manual backup trigger 語法仍未壓實

因此 `7868660.txt` 未落到 `/share/` 時，應先判成 **legacy firmware exception / capability gap**，不是 worker ingestion bug。

---

## 建議搭配方式

### 最簡單

- HA FTP server 收件
- cron / Node-RED / n8n 定時執行 worker
- Filebrowser 看 archive
- private Git remote 保存歷史

### 後續再補

- snapshot metadata schema
- HA device binding
- inventory export 讀 snapshot 狀態
- HA event / sensor / compare UI

---

## 結論

這個 worker 的角色就是：

> **先把 EMOS backup 可靠地變成可版控的 snapshot 歷史。**

第一版做到這樣，就已經夠值了。
