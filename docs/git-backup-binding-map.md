# EMOS Backup Binding Map

Last updated: 2026-04-10

這份文件定義 backup worker 的 **binding map**。

目的很單純：

> 讓 snapshot metadata 不只知道 `serial`，還能對上 `host`、`HA device`、`base entities`。

這是後面做 compare / snapshot overlay / rollback UI 的基礎。

---

## 為什麼需要 binding map

光靠 `7432284.txt` 這種檔名，只知道：

- serial

但後面真正會用到的是：

- 這台設備在現場叫什麼
- 它在 HA 裡綁到哪個 device
- 哪些 entity 是 HA 原生 MQTT 的 base mirror
- 它屬於哪個 site

所以 worker 現在支援讀結構化 binding map。

---

## 推薦檔名

例如：

```text
/config/ha-unircon/binding-map.json
```

repo 內範例：

- `tools/examples/binding-map.sample.json`

---

## 支援兩種格式

### 1. 舊格式，只有 serial -> host

```json
{
  "7432284": "Relay-685D"
}
```

這種格式仍可用，適合最簡版。

### 2. 新格式，結構化 binding

```json
{
  "7432284": {
    "host": "Relay-685D",
    "site": "ha-lab",
    "ha_device_id": "mqtt_7432284_device_id",
    "mqtt_identifier": "7432284",
    "manufacturer": "UNiNUS",
    "model": "UB-R5301",
    "sw_version": "3.65.3(M-IH)E.w3.s8",
    "base_entities": [
      "device_tracker.relay_685d_relay_685d_state",
      "switch.relay_685d_ou0_relay00",
      "sensor.relay_685d_s0_wifi",
      "sensor.relay_685d_s1_wifi"
    ],
    "notes": "bound to HA native MQTT device mirror"
  }
}
```

---

## 欄位說明

- `host`
  - 運維層看到的設備名稱
- `site`
  - 場域或群組名稱
- `ha_device_id`
  - HA device registry 的 device id
- `mqtt_identifier`
  - HA MQTT / device identifier
- `manufacturer`
  - 例如 `UNiNUS`
- `model`
  - 例如 `UB-R5301`
- `sw_version`
  - 韌體版本
- `base_entities`
  - 這台設備在 HA 原生 MQTT 層已存在的 entity ids
- `notes`
  - 補充說明

---

## worker 怎麼用

### CLI

```bash
node tools/emos_backup_worker.mjs --root /share/emostore --binding-map /config/ha-unircon/binding-map.json
```

### wrapper / env

```bash
export EMOS_BACKUP_BINDING_MAP=/config/ha-unircon/binding-map.json
bash tools/run_emos_backup_scan.sh
```

相容舊變數：

- `EMOS_BACKUP_HOST_MAP`

但新建議請用：

- `EMOS_BACKUP_BINDING_MAP`

---

## metadata v2

有 binding map 時，worker 會在 metadata 裡補出：

- `metadata_schema_version: 2`
- `site`
- `binding_map_path`
- `ha_device_id`
- `mqtt_identifier`
- `base_entities`
- `device_identity`
- `binding`

也就是說，後面如果 HA overlay 要讀 snapshot，不用只靠檔名猜。

---

## 設計原則

這份 binding map 的角色不是替代 HA registry。

它只是 **backup worker 這條線的對照表**，把：

- serial
- host
- HA device
- base entities

先穩定綁起來。

真正的 source of truth 還是：

- HA device registry
- HA entity registry
- HA MQTT integration

binding map 只是目前最務實的橋接層。

若不想手刻，可先用：

- `docs/ha-binding-candidate-exporter.md`
- `unircon.export_binding_candidates`

先從 HA registry 吐出候選，再人工確認。

---

## 下一步

等這份 binding map 穩定後，後面可再往下做：

1. 自動從 HA 匯出 binding 候選
2. snapshot 對應到 HA device page
3. config compare UI
4. rollback workflow

---

## 一句話版

> **binding map 是讓 backup snapshot 正式接上 HA identity 的第一條橋。**
