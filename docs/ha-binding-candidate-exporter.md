# HA Binding Candidate Exporter

Last updated: 2026-04-10

這個 exporter 的目的，是幫 `ha-unircon` 把目前已知的：

- host
- token / serial
- runtime state

拿去和 HA 內建的：

- device registry
- entity registry

做一次 **候選綁定比對**，吐出一份可直接拿來整理 binding map 的 event payload。

---

## 為什麼先做 exporter

手刻 binding map 當然可以，但台數一多很快會煩。

而且現場其實常常已經有：

- HA MQTT discovery 建好的 device
- 現成 entity
- recorder history

如果不先把這些已有資料收進來，後面 snapshot compare / rollback UI 會一直重複對 identity。

所以這一步的定位很明確：

> **先把候選綁定整理出來，不急著自動寫回。**

先看，再決定。

---

## Service

```yaml
service: unircon.export_binding_candidates
```

另外兩個更落地的 service：

```yaml
service: unircon.generate_binding_map
```

```yaml
service: unircon.save_binding_map
```

可選欄位：

```yaml
service: unircon.export_binding_candidates
data:
  hosts:
    - Relay-685D
    - sensor01
```

如果不帶 `hosts`，就會對目前 config entry 裡全部已配置 host 盤一次。

---

## 輸出事件

Service 執行後，會 fire：

```text
unircon_binding_candidates_exported
```

payload 主要欄位：

- `entry_id`
- `hosts`
- `binding_map`
- `binding_map_json`
- `unresolved_hosts`
- `candidates`

---

## generate_binding_map

如果你不要完整 candidates，只想拿可直接用的 JSON，跑：

```yaml
service: unircon.generate_binding_map
data:
  hosts:
    - Relay-685D
```

它會 fire：

```text
unircon_binding_map_generated
```

主要欄位：

- `binding_map`
- `binding_map_json`
- `resolved`
- `unresolved_hosts`

這個很適合直接接 automation / notification / clipboard workflow。

---

## save_binding_map

如果你要直接把結果存成檔案：

```yaml
service: unircon.save_binding_map
data:
  path: unircon/binding-map.generated.json
  overwrite: true
```

它會 fire：

```text
unircon_binding_map_saved
```

預設路徑：

```text
config/unircon/binding-map.generated.json
```

規則：

- `path` 可省略
- 相對路徑會解到 HA `config/` 底下
- 絕對路徑也可用
- 預設不覆蓋既有檔案
- 要覆蓋時明確帶 `overwrite: true`

---

## binding_map 是什麼

`binding_map` 是 exporter 幫你先整理好的「第一順位建議」。

條件是：

- 這個 host 已知 token / serial
- 在 HA registry 找得到至少一個候選 device

那它就會直接產出像這樣的結構：

```json
{
  "7432284": {
    "host": "Relay-685D",
    "site": null,
    "ha_device_id": "abc123",
    "mqtt_identifier": "7432284",
    "manufacturer": "UNiNUS",
    "model": "UB-R5301",
    "sw_version": "3.65.3(M-IH)E.w3.s8",
    "base_entities": [
      "device_tracker.relay_685d_relay_685d_state",
      "switch.relay_685d_ou0_relay00"
    ],
    "notes": "identifier matches token; manufacturer is UNiNUS"
  }
}
```

這份不是最後真值，但已經很接近可以落地成 binding map。

---

## candidates 內容

每個 host 下面會有完整候選列表。

每個 candidate 會帶：

- `score`
- `reasons`
- `ha_device_id`
- `device_name`
- `manufacturer`
- `model`
- `sw_version`
- `mqtt_identifier`
- `identifiers`
- `entity_ids`
- `entity_domains`
- `entity_platforms`
- `is_mqtt_device`
- `suggested_binding`

也就是說，不只告訴你「猜這台是誰」，還會把依據一起給你。

---

## 目前比對規則

目前是 heuristic scoring，不是硬綁：

1. **identifier / token match**
   - 分數最高
2. **device name match host**
3. **model match runtime state**
4. **firmware match runtime state**
5. **manufacturer = UNiNUS**

所以它是：

> **候選整理器，不是自動覆寫器。**

這樣比較安全。

---

## unresolved_hosts

這裡會列出還不能穩定出 binding 的 host。

例如：

- 還沒有 token
- 找不到 registry candidate

這份清單很重要，因為它就是下一輪要補資料的目標。

---

## 建議流程

1. 先跑 `unircon.request_token` / `run_health_check`
2. 再跑 `unircon.export_binding_candidates`
3. 看 event payload
4. 跑 `generate_binding_map` 或 `save_binding_map`
5. 交給 backup worker 的 `EMOS_BACKUP_BINDING_MAP`

---

## 和 backup worker 的關係

這個 exporter 是 **HA 端 identity 收斂器**。

backup worker 是 **snapshot / diff / Git pipeline**。

兩者接起來後，整條路徑才會完整：

```text
HA registry
  -> binding candidates
  -> binding-map.json
  -> backup worker metadata v2
  -> snapshot compare / rollback UI
```

---

## 一句話版

> **這個 service 是把 HA 已知 device/entity 現況，整理成可落地的 binding-map 候選。**
