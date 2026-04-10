# HA Backup Compare and Restore Preview Workflow

Last updated: 2026-04-10

這份文件回答的是：

> backup 已經進 HA overlay 了，接下來怎麼做 compare 與 restore 前置審查？

重點是：

- **先 compare，再 restore**
- `ha-unircon` 先做 **preview / audit / workflow entry**
- 真正的 device restore 仍保留 operator in the loop

---

## 內建 service

### 1. `unircon.compare_backups`

用途：

- 針對單一 host 比較兩個 snapshot
- 若沒指定 snapshot，預設取最新兩份
- 讀取 worker 的 `metadata/` 與 `normalized/` 內容
- fire event：`unircon_backup_compare`

事件內含：

- `current_snapshot`
- `previous_snapshot`
- `current_received_at`
- `previous_received_at`
- `line_additions`
- `line_removals`
- `diff_preview`
- `current_archive_path`
- `previous_archive_path`
- `current_metadata_path`
- `previous_metadata_path`

### 2. `unircon.generate_restore_preview`

用途：

- 針對某個 snapshot 產生 restore 前置預覽
- 不直接執行 restore
- fire event：`unircon_restore_preview_generated`

事件內含：

- `target_snapshot`
- `target_received_at`
- `target_archive_path`
- `target_metadata_path`
- `latest_snapshot`
- `warnings`
- `manual_steps`
- `required_policy_gate: true`

---

## 為什麼先不直接做 restore service

因為 restore 比 compare 危險很多。

目前 repo 已經有：

- policy gate
- backup metadata
- archive snapshot
- restore preview context

但還沒有一個 **已驗證、跨 firmware 一致、安全可回滾** 的 restore engine。

所以這一段先收斂成：

- compare service
- restore preview service
- audit event

這樣 UI / automation / operator 都有可靠入口，但不會過早把危險動作自動化。

---

## 最常見用法

### 比最新兩版

```yaml
service: unircon.compare_backups
data:
  host: Relay-685D
```

### 比指定兩版

```yaml
service: unircon.compare_backups
data:
  host: Relay-685D
  previous_snapshot: 2026-04-10T18-20-00+08-00
  current_snapshot: 2026-04-10T19-30-00+08-00
```

### 對某版做 restore preview

```yaml
service: unircon.generate_restore_preview
data:
  host: Relay-685D
  snapshot: 2026-04-10T18-20-00+08-00
```

---

## 建議操作順序

1. `unircon.sync_backup_status`
2. `unircon.compare_backups`
3. 人工確認 diff / archive / target host / serial
4. `unircon.generate_restore_preview`
5. 人工執行已核准的 device restore 流程
6. `unircon.run_health_check`
7. `unircon.sync_backup_status`

---

## 邊界

這一版不做：

- 自動 upload snapshot 回 device
- 自動執行 restore 命令
- 自動 rollback
- firmware-specific restore orchestration

這些等真正 field workflow 收斂後，再往下一版做。

---

## 一句話版

> 這一層先把 restore 做成 **可比較、可審查、可追蹤**，而不是直接做成危險自動化。
