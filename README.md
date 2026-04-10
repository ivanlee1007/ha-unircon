# ha-unircon

Home Assistant Integration for UNiNUS Remote Console — 透過 HA 管理 UNiNUS IoT 設備。

目前定位：**EMOS / UNiNUS 設備運維中台（operations cockpit）**，不是完整 fleet/OTA backend 的替代品。

架構基線補充：對於 **已經由 HA 原生 MQTT discovery 註冊的 EMOS 設備**，`ha-unircon` 後續應優先扮演 **operations overlay layer**，不要再重建一套平行 device mirror。詳見 `docs/ha-mqtt-overlay-strategy.md`。

## 功能

- **Config Flow**：HA UI 一鍵設定 MQTT Broker + 設備清單（目前單一實例）
- **Console Sensor**：每台設備的即時 console 輸出
- **Status Sensor**：設備連線狀態
- **Fleet Summary Sensor**：整體設備 online / stale / offline 摘要
- **Audit Log Sensor**：整合層服務操作與盤點輸出紀錄
- **Last Seen / Firmware Sensors**：每台設備最後回報時間、已知韌體版本
- **Dangerous Command Policy Gate**：對 `write erase` / `config restore` / `reload` / `copy ...` 等高風險命令做攔截與暫時核准
- **Token Text**：設備序號顯示與手動設定
- **Command Buttons**：Enable / Show Version / URCON Neighbors / Backup 等快按
- **Services**：下指令、批次處理、MQTT 測試發佈、鄰居探索、健康檢查、inventory 匯出、部署檔生成、動態新增設備
- **Custom Card**（v2）：四個分頁
  - 🖥️ **主控台**：即時串流 + 指令輸入 + Hot Keys + 歷史命令 ↑↓
  - 📋 **部署檔**：表單填寫 → 生成 / 複製 / 下載 deploy config
  - 📦 **批次處理**：多主機 × 多指令一鍵執行
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
| `sensor.unircon_<host>_console` | sensor | Console 輸出（含 200 行歷史） |
| `sensor.unircon_<host>_status` | sensor | 設備狀態（online / offline） |
| `sensor.unircon_<host>_last_seen` | sensor | 最後回報時間（integration 收到訊息） |
| `sensor.unircon_<host>_firmware` | sensor | 已知韌體版本（從 console 輸出解析） |
| `text.unircon_<host>_token` | text | 設備序號 |
| `button.unircon_<host>_enable` | button | Enable 設備 |
| `button.unircon_<host>_show_version` | button | 顯示版本 |
| `button.unircon_<host>_show_result` | button | 顯示結果 |
| `button.unircon_<host>_health_check` | button | 對單台設備執行健康檢查 |
| `button.unircon_<host>_urcon_neighbors` | button | URCON 鄰居探索 |
| `button.unircon_<host>_backup` | button | 備份 |

### Per-Integration（每個 entry 一組）

| Entity | 類型 | 說明 |
|--------|------|------|
| `sensor.unircon_<entry>_fleet_summary` | sensor | 全體設備 online/stale/offline 摘要 |
| `sensor.unircon_<entry>_audit_log` | sensor | 最新 audit 記錄與最近 20 筆整合層操作 |

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
| `unircon.export_inventory` | 匯出目前 inventory / runtime summary（event） |
| `unircon.generate_deploy` | 生成設備部署檔（結果透過 event 傳回） |
| `unircon.add_device` | 動態新增一台設備到整合中 |

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
