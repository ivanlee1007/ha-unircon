# HA MQTT Overlay Strategy for EMOS / UNiNUS Devices

Last updated: 2026-04-10

## Why this document exists

`ha-unircon` 現在正往「EMOS / UNiNUS 運維中台」方向擴充。

但在實際 HA 現場（192.168.1.222）確認後，**EMOS device 的基礎 device mirror 已經由 HA 原生 MQTT integration 提供**。如果 `ha-unircon` 再自己生成一套平行的基礎 entity，會造成：

- entity 重複
- device identity 分裂
- recorder/history 分散
- 使用者不知道哪一套才是真值
- 後續 snapshot / rollback / dashboard 都更難維護

所以後續設計要改成：

> **HA 原生 MQTT = base device mirror**  
> **ha-unircon = operations overlay layer**

不是再造一套 device mirror。

---

## Verified live finding: UB-R5301 already exists in HA via MQTT

Target HA: `http://192.168.1.222:8123`
Target device: `UB-R5301 / Relay-685D / SN 7432284`

### Device registry

Live HA already has this MQTT device record:

- **name**: `Relay-685D`
- **manufacturer**: `UNiNUS`
- **model**: `UB-R5301`
- **sw_version**: `3.65.3(M-IH)E.w3.s8`
- **identifier**: `mqtt / 7432284`
- **config entry domain**: `mqtt`

### Entity registry

Live HA already provides these entities for the test node:

1. `device_tracker.relay_685d_relay_685d_state`
   - state: `online`
2. `switch.relay_685d_ou0_relay00`
   - state: `off`
3. `sensor.relay_685d_s0_wifi`
   - state: `-57 dBm`
4. `sensor.relay_685d_s1_wifi`
   - state: `-57 dBm`

### Recorder / history

Recent history is already present in HA recorder:

- device online/offline state
- relay output state
- Wi-Fi RSSI series

This means HA already owns the baseline timeline for this node.

---

## Design rule 1: do not duplicate base MQTT entities

`ha-unircon` should **not** create another copy of:

- online/offline base connectivity state
- relay mirror entities
- RSSI / telemetry entities already provided by MQTT discovery
- base device identity already represented in device registry

### Bad outcome to avoid

If `ha-unircon` creates `sensor.unircon_<host>_status` while HA already has a real MQTT-backed `device_tracker` or `binary_sensor` equivalent, users get:

- two online/offline states
- different last_changed timelines
- dashboards mixing overlay state with source state
- recorder duplication

### Better pattern

`ha-unircon` may still keep **internal runtime state** in memory for orchestration, but should avoid presenting duplicated “source-of-truth” entities when HA already has them.

---

## Design rule 2: `ha-unircon` should own operations, not mirroring

`ha-unircon` is still valuable, but at a different layer.

### Good `ha-unircon` responsibilities

- console workflow
- command execution UI / services
- URCON discovery / session tooling
- dangerous command policy gate
- approval workflow
- audit trail
- health-check orchestration
- inventory export
- deploy / backup / snapshot workflows
- future config diff / rollback workflow

### Not the primary job of `ha-unircon`

- rebuilding MQTT-discovered switch/sensor/device entities
- storing the canonical connectivity history when MQTT entities already do it
- representing basic hardware mirror data that HA already exposes cleanly

---

## Proposed layering model

### Layer A. Source layer (owned by MQTT integration)

Owned by HA native MQTT / discovery:

- device registry identity
- discovered switch/sensor/device_tracker entities
- recorder history of those entities
- native entity names / availability / restore behavior

### Layer B. Overlay layer (owned by `ha-unircon`)

Owned by `ha-unircon`:

- command and console services
- overlay audit log
- operation approvals
- fleet actions
- snapshot metadata
- deploy / backup workflows
- command history / operator notes / policy decisions

### Layer C. Governance layer (future, possibly outside HA)

May eventually live outside HA:

- config version store
- long-term audit DB
- rollback engine
- OTA rollout orchestration
- policy backend / site-level governance

---

## Mapping strategy: how `ha-unircon` should bind to existing HA devices

When possible, `ha-unircon` should bind an operation target to an existing HA device/entity set instead of creating a parallel identity.

### Preferred matching keys

1. **serial number / device identifier**
   - Example: MQTT identifier `7432284`
   - Best stable key when available

2. **hostname / host topic name**
   - Example: `Relay-685D`
   - Good operational key, but not always globally stable

3. **model + firmware + topic pattern**
   - Only fallback metadata, not strong identity alone

### Practical note

Current `ha-unircon` host list is host-name based, while live HA MQTT discovery for EMOS already knows the device object.

So future work should introduce a binding model like:

- `host`: runtime command target name
- `serial` / `device_identifier`: canonical hardware identity
- `ha_device_id`: bound HA device registry id
- `base_entities`: references to the MQTT-owned core entities

---

## Entity strategy going forward

### Keep as `ha-unircon` entities

These are overlay-style and still make sense:

- fleet summary
- audit log
- approval / policy state
- snapshot state
- last command result
- last command timestamp
- deploy/backup workflow result

### Re-evaluate / avoid duplicating

These should not blindly duplicate MQTT-native entities:

- per-host generic online/offline status
- per-host firmware if already available in HA device registry
- per-host telemetry mirrors that already exist as MQTT entities

### Important nuance

An overlay entity is acceptable if it represents a **different semantic layer**.

Example:

- MQTT entity says device is `online`
- `ha-unircon` overlay may say `ops_health = stale` because token request failed or last console workflow timed out

That is not duplication, because it answers a different question.

---

## Recommended next implementation phases

### Phase 1. Binding layer

Add a mapping layer between `ha-unircon` host targets and HA device registry / entity registry records.

Goals:

- discover whether a host already has an MQTT-backed HA device
- store binding metadata
- expose this mapping in inventory export

### Phase 2. Stop creating duplicate source-style entities

Refactor entity model so new overlay entities do not mirror MQTT base states unnecessarily.

Possible direction:

- keep integration-level aggregate entities
- keep workflow/audit/policy entities
- reduce generic per-host mirror entities where HA already has stronger source entities

### Phase 3. Build snapshot / diff workflow on top of the bound HA device

Once a host is bound to a real HA device:

- show linked base entities
- capture snapshot metadata
- compare operation-time state with recorder history / current base state
- build safe rollback workflow

---

## Concrete decision taken on 2026-04-10

For EMOS devices already registered through HA MQTT discovery:

**Do not design `ha-unircon` as a second device mirror.**

Design it as:

- **operations cockpit**
- **policy/audit overlay**
- **workflow layer bound to an existing HA MQTT device**

This is the baseline assumption for future `ha-unircon` changes.
