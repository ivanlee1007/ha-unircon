# ha-unircon

Home Assistant Integration for UNiNUS Remote Console — 透過 HA 管理 UNiNUS IoT 設備。

## 功能

- **Config Flow**：HA UI 一鍵設定 MQTT Broker + 設備清單
- **Console Sensor**：每台設備的即時 console 輸出
- **Status Sensor**：設備連線狀態
- **Token Text**：設備序號顯示與手動設定
- **Command Buttons**：Enable / Show Version / URCON Neighbors / Backup 等快按
- **Services**：下指令、批次處理、MQTT 測試發佈、鄰居探索、部署檔生成、動態新增設備
- **Custom Card**（v2）：四個分頁
  - 🖥️ **主控台**：即時串流 + 指令輸入 + Hot Keys + 歷史命令 ↑↓
  - 📋 **部署檔**：表單填寫 → 生成 / 複製 / 下載 deploy config
  - 📦 **批次處理**：多主機 × 多指令一鍵執行
  - 📡 **MQTT**：Broker 設定 + 測試發佈 + URCON 鄰居探索（可一鍵加入主機清單）

## 安裝

### HACS Custom Repository

1. HACS → Custom repositories
2. 加入 `https://github.com/ivanlee1007/ha-unircon`，Category：`Integration`
3. 安裝 **UNiNUS Remote Console**
4. 重啟 HA
5. 設定 → 整合 → 新增「UNiNUS Remote Console」

### 手動安裝

將 `custom_components/unircon/` 複製到 HA 的 `config/custom_components/`。

## Entities

### Per-Device（每台主機自動產生）

| Entity | 類型 | 說明 |
|--------|------|------|
| `sensor.unircon_<host>_console` | sensor | Console 輸出（含 200 行歷史） |
| `sensor.unircon_<host>_status` | sensor | 設備狀態（online / offline） |
| `text.unircon_<host>_token` | text | 設備序號 |
| `button.unircon_<host>_enable` | button | Enable 設備 |
| `button.unircon_<host>_show_version` | button | 顯示版本 |
| `button.unircon_<host>_show_result` | button | 顯示結果 |
| `button.unircon_<host>_urcon_neighbors` | button | URCON 鄰居探索 |
| `button.unircon_<host>_backup` | button | 備份 |

## Services

| Service | 說明 |
|---------|------|
| `unircon.send_command` | 對單台設備下指令 |
| `unircon.batch_command` | 批次對多台設備下指令 |
| `unircon.request_token` | 要求設備序號 |
| `unircon.mqtt_publish` | MQTT 測試發佈 |
| `unircon.collect_neighbors` | URCOM 鄰居探索 |
| `unircon.generate_deploy` | 生成設備部署檔（結果透過 event 傳回） |
| `unircon.add_device` | 動態新增一台設備到整合中 |

## Dashboard Card

```yaml
type: custom:unircon-console-card
title: UNiNUS Console
hosts:
  - sensor01
  - sensor02
broker:
  host: 192.168.1.222
  port: 9001
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
```

## 相關

- 原始 Console：[UNiNUS Remote Console v24](https://github.com/ivanlee1007/ha-unircon)
- MQTT Protocol：`ha/sub/<host>` / `ha/pub/<host>/console/` / `ha/pubrsp/<host>`

## License

MIT
