# ha-unircon

Home Assistant Integration for UNiNUS Remote Console — 透過 HA 管理 UNiNUS IoT 設備。

目前定位：**EMOS / UNiNUS 設備運維中台（operations cockpit）**，不是完整 fleet/OTA backend 的替代品。

架構基線補充：對於 **已經由 HA 原生 MQTT discovery 註冊的 EMOS 設備**，`ha-unircon` 後續應優先扮演 **operations overlay layer**，不要再重建一套平行 device mirror。詳見 `docs/ha-mqtt-overlay-strategy.md`。

## 功能

- **Config Flow**：HA UI 一鍵設定 MQTT Broker + 設備清單（目前單一實例）
- **Console Sensor**：每台設備的即時 console 輸出
- **Status Sensor**：設備連線狀態
- **Fleet Summary Sensor**：整體設備 online / stale / offline 摘要
- **Backup Summary / Backup Status Sensors**：顯示最新 snapshot change_type、SHA、archive 路徑與同步時間
- **Audit Log Sensor**：整合層服務操作與盤點輸出紀錄
- **Last Seen / Firmware Sensors**：每台設備最後回報時間、已知韌體版本
- **Dangerous Command Policy Gate**：對 `write erase` / `config restore` / `reload` / `copy ...` 等高風險命令做攔截與暫時核准
- **Token Text**：設備序號顯示與手動設定
- **Command Buttons**：Enable / Show Version / URCON Neighbors / Backup 等快按
- **Services**：下指令、批次處理、MQTT 測試發佈、鄰居探索、健康檢查、binding map 生成、backup status 同步、snapshot compare、restore preview、inventory 匯出、部署檔生成、動態新增設備
- **Custom Card**（v3）：五個分頁
  - 🖥️ **主控台**：即時串流 + 指令輸入 + Hot Keys + 歷史命令 ↑↓
  - 📋 **部署檔**：表單填寫 → 生成 / 複製 / 下載 deploy config
  - 📦 **批次處理**：多主機 × 多指令一鍵執行
  - 🗂️ **備份**：sync backup status / compare snapshots / restore preview
  - 📡 **MQTT**：Broker 設定 + 測試發佈 + URCON 鄰居探索（可一鍵加入主機清單）

## 這個 integration 適合做什麼

適合：
- 集中式設備盤點與健康檢查
- 日常運維操作入口
- 批次指令與批次檢查
- 基本 audit trail
- 設備 console / MQTT / URCON 作業面板

不建議單獨扛：
- 完整企業級 RBAC
- 多租戶隔離
- 完整 OTA 波次治理
- 長期 config version store / rollback engine

這些建議由外部 backend 承接，HA / `ha-unircon` 當前台與操作入口。

## Design Notes

- `docs/ha-mqtt-overlay-strategy.md`：HA 原生 MQTT 與 `ha-unircon` 的分層策略，避免重複造輪子
- `docs/emos-backup-versioning-architecture.md`：EMOS 備份落地到 HA 同機 FTP 後，如何接 snapshot / diff / Git 版本控制
- `docs/git-backup-runbook.md`：Git 簡版備份版控的實作 runbook，含目錄、檔名、metadata、commit 規則
- `docs/git-backup-worker.md`：starter worker 的 CLI 用法與目前能力邊界
- `docs/git-backup-automation.md`：在 HA 主機上用 shell / cron / Node-RED / n8n 跑 worker 的建議做法
- `docs/git-backup-binding-map.md`：把 serial 正式對到 host / HA device / base entities 的 binding map 規格
- `docs/ha-binding-candidate-exporter.md`：從 HA registry 匯出 binding candidate，減少手刻 binding map
- `docs/ha-binding-backup-pipeline.md`：把 `save_binding_map` 和 backup worker 串成單條可排程流程
- `docs/ha-backup-compare-restore.md`：snapshot compare 與 restore preview 的 backend workflow

> 注意：`ha-unircon` 目前除了 `add_extra_js_url()`，也會透過 HA 的 Lovelace resource storage API 確保自己的卡片資源存在，避免 resource 沒持久化時卡片根本不載入。

> 補充：console card 在 `config.hosts` 空白時，現在會自動從 HA 內已建立的 `UNiNUS` entities 反推 host 清單；若有多個 config entry，建議在 card config 補 `entry_id` 來精準綁定。

## 使用前預先需求

### 必要

1. **MQTT broker**
   - `ha-unircon` 後端服務依賴 MQTT/TCP
   - HA add-on 可用：**Mosquitto broker**（最直接）
   - 若你已有外部 broker，也可直接填既有 broker

2. **已知可連線的 EMOS / UNiNUS 裝置**
   - 至少要能透過 MQTT / URCON / console topic 跟 HA 所在網段互通
   - 若裝置已經用 HA 原生 MQTT discovery 註冊到 HA，`ha-unircon` 會更適合扮演 operations overlay

### 建議

1. **Terminal & SSH** 或 **Advanced SSH & Web Terminal**
   - 方便查 log、看備份檔、手動驗證 deploy / backup 行為

2. **Filebrowser**
   - 方便直接檢查 backup landing files、snapshot archive、deploy 輸出

3. **FTP server**（如果你要接 EMOS config backup）
   - 建議把 EMOS FTP backup server 指到 HA 同機器
   - 這樣 HA 主機可以成為 EMOS backup ingest point
   - 但請注意：**FTP 本身不是版本控制**，只是收件箱

### 如果你要先做「Git 簡版備份版控」

建議 HA 同機至少具備以下能力：

1. **MQTT broker**
   - 給 `ha-unircon` 本體使用

2. **FTP server**
   - 接 EMOS backup 上傳

3. **檔案存取工具**
   - 例如 **Filebrowser** / Samba / SSH
   - 用來檢查 `inbox/`, `latest/`, `archive/` 這些資料夾

4. **可執行腳本/自動化的環境**
   - 例如 **Terminal & SSH**、**Advanced SSH & Web Terminal**、**Node-RED**、**n8n**
   - 用來做 watcher / snapshot copy / hash / Git commit

### 關於資料儲存

- **Git + 檔案 archive**：最適合先做簡版 config versioning
- **MariaDB / MySQL**：適合之後再補 metadata / audit / workflow state
- **InfluxDB**：適合 telemetry / RSSI / success-rate 等時間序列觀測，不適合當 config version store

相關設計文件：

- `docs/ha-mqtt-overlay-strategy.md`
- `docs/emos-backup-versioning-architecture.md`
- `docs/git-backup-runbook.md`
- `docs/git-backup-worker.md`
- `docs/git-backup-automation.md`
- `docs/git-backup-binding-map.md`
- `docs/ha-binding-candidate-exporter.md`
- `docs/ha-binding-backup-pipeline.md`

### 內建 starter worker

repo 目前已提供一個 Git 簡版備份 worker：

- `tools/emos_backup_worker.mjs`

以及一條直接把 HA binding map 串進 worker 的 pipeline runner：

- `tools/run_binding_backup_pipeline.mjs`

可用來掃描 FTP landing inbox，建立 archive / metadata / diff / Git commit。

若要讓 metadata 接上 HA identity，建議再搭配：

- `tools/examples/binding-map.sample.json`

最簡單用法：

```bash
npm run backup:scan -- --root /share/emostore --inbox /share --commit
```

說白一點，現在預設假設是：**EMOS 裝置把 FTP backup 丟到 `/share/<SN>.txt`，worker 再從 `/share` 吃 raw landing files，並把整理後的 archive / metadata / diff 寫到 `/share/emostore/repo/`。**

若要用 wrapper 直接跑排程友善版本：

```bash
npm run backup:run
```

若要先由 HA service 更新 binding map，再把同一路徑直接餵給 worker：

```bash
npm run backup:pipeline
```

更多實際排程方式見：`docs/git-backup-automation.md`

## 安裝

### HACS Custom Repository

1. HACS → Custom repositories
2. 加入 `https://github.com/ivanlee1007/ha-unircon`，Category：`Integration`
3. 安裝 **UNiNUS Remote Console**
4. 重啟 HA
5. 設定 → 整合 → 新增「UNiNUS Remote Console」
6. 若你的 URCON discovery 需要固定 callback host/IP，可在安裝時填入 `Discovery Host Name` 與 `Callback IP / Host`

### 手動安裝

將 `custom_components/unircon/` 複製到 HA 的 `config/custom_components/`。

## Entities

### Per-Device（每台主機自動產生）

| Entity | 類型 | 說明 |
|--------|------|------|
| `sensor.uninus_<host>_console` | sensor | Console 輸出（含 200 行歷史） |
| `sensor.uninus_<host>_status` | sensor | 設備狀態（online / offline） |
| `sensor.uninus_<host>_last_seen` | sensor | 最後回報時間（integration 收到訊息） |
| `sensor.uninus_<host>_firmware` | sensor | 已知韌體版本（從 console 輸出解析） |
| `text.uninus_<host>_token` | text | 設備序號 |
| `button.uninus_<host>_enable` | button | Enable 設備 |
| `button.uninus_<host>_show_version` | button | 顯示版本 |
| `button.uninus_<host>_show_result` | button | 顯示結果 |
| `button.uninus_<host>_health_check` | button | 對單台設備執行健康檢查 |
| `button.uninus_<host>_urcon_neighbors` | button | URCON 鄰居探索 |
| `button.uninus_<host>_backup` | button | 備份 |

### Per-Integration（每個 entry 一組）

| Entity | 類型 | 說明 |
|--------|------|------|
| `sensor.uninus_<entry>_fleet_summary` | sensor | 全體設備 online/stale/offline 摘要 |
| `sensor.uninus_<entry>_backup_summary` | sensor | 全體設備最新 backup sync/change 摘要 |
| `sensor.uninus_<entry>_audit_log` | sensor | 最新 audit 記錄與最近 20 筆整合層操作 |

另外每台主機會多一個：

| Entity | 類型 | 說明 |
|--------|------|------|
| `sensor.uninus_<host>_backup` | sensor | 最新 backup change_type / snapshot 狀態 |

## Services

| Service | 說明 |
|---------|------|
| `unircon.send_command` | 對單台設備下指令 |
| `unircon.batch_command` | 批次對多台設備下指令 |
| `unircon.request_token` | 要求設備序號 |
| `unircon.mqtt_publish` | MQTT 測試發佈 |
| `unircon.collect_neighbors` | URCOM 鄰居探索 |
| `unircon.approve_operation` | 暫時核准某台設備的高風險命令 |
| `unircon.run_health_check` | 對指定設備做 token/version/clock/result 健康檢查 |
| `unircon.sync_backup_status` | 從 worker metadata 匯回最新 backup 狀態 |
| `unircon.compare_backups` | 比較某台設備兩個 snapshot，產出 diff preview event |
| `unircon.generate_restore_preview` | 產出 restore 前置預覽，不直接執行還原 |
| `unircon.export_inventory` | 匯出目前 inventory / runtime summary（event） |
| `unircon.export_binding_candidates` | 從 HA device/entity registry 匯出 binding-map 候選（event） |
| `unircon.generate_binding_map` | 產出可直接落地的 binding-map JSON（event） |
| `unircon.save_binding_map` | 直接把 binding-map JSON 存到 HA 主機檔案 |
| `unircon.generate_deploy` | 生成設備部署檔（結果透過 event 傳回） |
| `unircon.add_device` | 動態新增一台設備到整合中 |

### Binding candidate exporter 範例

先讓 integration 拿到 token / runtime state 後，可直接對 HA registry 盤一輪：

```yaml
service: unircon.export_binding_candidates
data:
  hosts:
    - Relay-685D
```

會 fire event：`unircon_binding_candidates_exported`

事件內含：
- `binding_map`：第一順位建議綁定
- `unresolved_hosts`：還缺 token 或找不到候選的 host
- `candidates`：完整候選清單與比對理由

如果你只想拿乾淨 JSON：

```yaml
service: unircon.generate_binding_map
data:
  hosts:
    - Relay-685D
```

會 fire：`unircon_binding_map_generated`

如果你要直接落地成檔案：

```yaml
service: unircon.save_binding_map
data:
  path: unircon/binding-map.generated.json
  overwrite: true
```

會 fire：`unircon_binding_map_saved`

### Backup status sync 範例

當 worker 跑完後，可把最新 metadata 匯回 HA：

```yaml
service: unircon.sync_backup_status
data:
  metadata_root: /share/emostore/repo/metadata
```

會 fire：`unircon_backup_status`

之後可以直接在：
- `sensor.unircon_<entry>_backup_summary`
- `sensor.unircon_<host>_backup`

看到最新 snapshot 狀態。

### Backup compare 範例

```yaml
service: unircon.compare_backups
data:
  host: Relay-685D
```

會 fire：`unircon_backup_compare`

事件內含：
- `current_snapshot` / `previous_snapshot`
- `line_additions` / `line_removals`
- `diff_preview`
- `current_archive_path` / `previous_archive_path`

### Restore preview 範例

```yaml
service: unircon.generate_restore_preview
data:
  host: Relay-685D
  snapshot: 2026-04-10T19-30-00+08-00
```

會 fire：`unircon_restore_preview_generated`

事件內含：
- target snapshot / archive / metadata 路徑
- warning 清單
- manual restore steps
- `required_policy_gate: true`

## Policy Gate

目前 integration 會把下列命令族視為高風險：
- `write erase*`
- `write default`
- `config restore*`
- `restore factory`
- `reload` / `reboot`
- `copy ...`
- `exec autodeploy`

預設行為：
- 一般 `send_command` / `batch_command` 遇到這些命令時會先擋下
- 需要用 `confirm: true` 明確放行，或先呼叫 `unircon.approve_operation`
- 所有放行 / 擋下行為都會寫進 audit log

### 危險操作放行範例

```yaml
service: unircon.approve_operation
data:
  host: sensor01
  command: write erase all force
  ttl_seconds: 180
  note: 現場維修更換前清機
```

接著在核准時效內再送命令：

```yaml
service: unircon.send_command
data:
  host: sensor01
  command: write erase all force
```

或直接單次明確放行：

```yaml
service: unircon.send_command
data:
  host: sensor01
  command: reload
  confirm: true
```

### Integration 設定

在 HA 整合的 **Configure / Options** 可調：
- 是否啟用 dangerous-command policy gate
- 暫時核准視窗秒數（approval window）

## Dashboard Card

```yaml
type: custom:unircon-console-card
title: UNiNUS Console
hosts:
  - sensor01
  - sensor02
broker:
  host: 192.168.1.222
  port: 1884
  username: admin
  password: "uninus@99"
  domain: uninus
```

### Card 分頁說明

| Tab | 功能 |
|-----|------|
| 🖥️ 主控台 | 即時 MQTT 串流、指令輸入（Ctrl+Enter 送出）、↑↓ 歷史、Hot Keys |
| 📋 部署檔 | 表單填寫 → 生成 → 複製 / 下載 deploy.txt |
| 📦 批次處理 | 主機清單 + 指令清單 → 逐一執行（每台 1.5s 間隔）|
| 📡 MQTT | Broker 連線設定 + 測試發佈 + 鄰居探索 → 一鍵加入主機清單 |

Card MQTT WebSocket 連線設定存在瀏覽器 localStorage，不影響 HA 後端。

注意：HA integration 後端服務（例如 `collect_neighbors`、`send_command`）使用的是原生 MQTT/TCP，不是瀏覽器 WebSocket，請優先設定 broker port 為 `1883`。卡片前端的 MQTT 分頁走的是 WebSocket，原版環境通常是 `1884`；目前卡片會優先嘗試 `ws://host:port`，再 fallback 到 `ws://host:port/mqtt`。後端 service 現在會在需要時自動重連 MQTT；透過 `unircon.add_device` 新增的主機也會持久寫回整合設定，不會因 reload 消失。

## 自動化範例

```yaml
# 每天凌晨 3 點自動備份
automation:
  - trigger:
      - platform: time
        at: "03:00:00"
    action:
      - service: unircon.send_command
        data:
          host: sensor01
          command: backup

# 批次 show version
  - trigger:
      - platform: time
        at: "08:00:00"
        days: [mon]
    action:
      - service: unircon.batch_command
        data:
          hosts: ["sensor01", "sensor02", "sensor03"]
          commands: ["sh ver", "sh result"]
          delay: 1

# 每 30 分鐘跑一次健康檢查
  - trigger:
      - platform: time_pattern
        minutes: "/30"
    action:
      - service: unircon.run_health_check
        data:
          delay: 1

# 設備離線通知
  - trigger:
      - platform: state
        entity_id: sensor.unircon_sensor01_status
        to: "offline"
    action:
      - service: notify.line_notify
        data:
          message: "⚠️ UNiNUS sensor01 離線"

# 鄰居探索 → 自動新增設備
  - trigger:
      - platform: event
        event_type: unircon_console
    condition:
      - condition: template
        value_template: >
          {{ 'Discovered neighbor' in trigger.event.data.get('data', {}).get('data', {}).get('output', '') }}
    action:
      - service: unircon.add_device
        data:
          host: "{{ trigger.event.data.host }}"

# 匯出 inventory 後寫入 logbook / 外部處理
  - trigger:
      - platform: event
        event_type: unircon_inventory_exported
    action:
      - service: logbook.log
        data:
          name: "UNiNUS Inventory"
          message: "已匯出 {{ trigger.event.data.inventory | count }} 台設備摘要"

# 高風險操作先核准再下發
  - alias: unircon_safe_reload_sensor01
    trigger: []
    action:
      - service: unircon.approve_operation
        data:
          host: sensor01
          command: reload
          ttl_seconds: 120
          note: 排程維護
      - service: unircon.send_command
        data:
          host: sensor01
          command: reload
```

## 相關

- 原始 Console：[UNiNUS Remote Console v24](https://github.com/ivanlee1007/ha-unircon)
- MQTT Protocol：`ha/sub/<host>` / `ha/pub/<host>/console/` / `ha/pubrsp/<host>`

## Roadmap direction

目前建議把 `ha-unircon` 視為：

- **HA 內就做**：fleet dashboard、health monitoring、batch ops、basic audit
- **HA + 外部 backend**：config versioning / rollback、policy gate、長期 audit store
- **不建議只放 HA**：完整 OTA orchestration、企業級 RBAC、多租戶治理

## License

MIT
