# ha-unircon

Home Assistant Integration for UNiNUS Remote Console — 透過 HA 管理 UNiNUS IoT 設備。

## 功能

- **Config Flow**：HA UI 一鍵設定 MQTT Broker + 設備清單
- **Console Sensor**：每台設備的即時 console 輸出
- **Status Sensor**：設備連線狀態
- **Token Text**：設備序號顯示與手動設定
- **Command Buttons**：Enable、Show Version、URCON Neighbors、Backup 等快按
- **Services**：下指令、批次處理、MQTT 測試發佈、鄰居探索
- **Custom Card**：互動式主控台 UI（指令輸入 + 即時輸出 + Hot Keys）

## 安裝

### HACS Custom Repository

1. HACS → Custom repositories
2. 加入 `https://github.com/ivanlee1007/ha-unircon`，Category：`Integration`
3. 安裝 **UNiNUS Remote Console**
4. 重啟 HA
5. 設定 → 整合 → 新增「UNiNUS Remote Console」

### 手動安裝

將 `custom_components/unircon/` 複製到 HA 的 `config/custom_components/`。

## 設定

### Config Flow

1. **MQTT 連線**：Broker 位址、Port、帳號密碼、URCON Domain
2. **設備清單**：每行一台主機名稱

### Entities（每台設備）

| Entity | 類型 | 說明 |
|--------|------|------|
| `sensor.unircon_<host>_console` | sensor | Console 輸出 |
| `sensor.unircon_<host>_status` | sensor | 設備狀態 |
| `text.unircon_<host>_token` | text | 設備序號 |
| `button.unircon_<host>_enable` | button | Enable 設備 |
| `button.unircon_<host>_show_version` | button | 顯示版本 |
| `button.unircon_<host>_show_result` | button | 顯示結果 |
| `button.unircon_<host>_urcon_neighbors` | button | URCON 鄰居探索 |
| `button.unircon_<host>_backup` | button | 備份 |

### Services

| Service | 說明 |
|---------|------|
| `unircon.send_command` | 對單台設備下指令 |
| `unircon.batch_command` | 批次對多台設備下指令 |
| `unircon.request_token` | 要求設備序號 |
| `unircon.mqtt_publish` | MQTT 測試發佈 |
| `unircon.collect_neighbors` | URCOM 鄰居探索 |

### Dashboard Card

```yaml
type: custom:unircon-console-card
title: UNiNUS Console
hosts:
  - sensor01
  - sensor02
broker:
  host: 192.168.1.222
  port: 1884
```

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

# 設備離線通知
  - trigger:
      - platform: state
        entity_id: sensor.unircon_sensor01_status
        to: "offline"
    action:
      - service: notify.line_notify
        data:
          message: "⚠️ UNiNUS sensor01 離線"
```

## 相關

- 原始 Console：UNiNUS Remote Console v24
- MQTT Protocol：`ha/sub/<host>` / `ha/pub/<host>/console/` / `ha/pubrsp/<host>`

## License

MIT
