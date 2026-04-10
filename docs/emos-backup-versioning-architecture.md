# EMOS Backup Versioning Architecture on Home Assistant Host

Last updated: 2026-04-10

## Executive summary

EMOS 裝置把 FTP backup server 指到 Home Assistant 同一台主機，**可以成為版本控制架構的基礎**，而且很合理。

但要先講清楚一件事：

> **FTP server 本身不是版本控制。**
>
> FTP 只是收件箱（ingest point）。
>
> 真正的版本控制來自後面的：
> - snapshot archive
> - metadata capture
> - diff pipeline
> - Git / version store

所以正確設計不是：

- EMOS → FTP → 完成

而是：

- EMOS → FTP inbox on HA host
- watcher / workflow detects new backup
- archive into immutable timestamped snapshot
- normalize / diff / classify
- commit to Git or store in version DB
- expose results back to HA / `ha-unircon`

---

## Why HA host is a good place for this

在實際場域裡，HA 主機常常已經同時承載：

- MQTT broker
- FTP server
- automation tools (Node-RED / n8n)
- file tools
- dashboards / notifications
- recorder / logs

對 EMOS 來說，這很適合拿來做：

- config backup landing zone
- deploy file generation
- snapshot metadata tracking
- diff / rollback workflow UI

也就是說，**HA 主機可以是 EMOS 維運資料平面的中心點**。

---

## Design goals

這套架構要解的不是「有沒有備份檔」，而是以下幾件事：

1. **保留歷史版本**，不能只有 latest
2. **保留原始檔**，方便真實 restore
3. **可比較差異**，知道哪次改了什麼
4. **能回到某個版本**，建立 rollback workflow 基礎
5. **能跟 HA / `ha-unircon` 對接**，在操作面上可見
6. **不要和 HA 原生 MQTT mirror 重複造輪子**

---

## Core architecture

## Layer 1. Ingest layer

負責接收裝置送來的 backup。

### Components

- EMOS device backup client
- FTP server on HA host

### Responsibility

- 接住來自裝置的備份檔
- 不做太多判斷
- 儘量保留原始狀態

### Important rule

FTP landing file 不能直接當版本庫。

例如這種檔案：

- `share/7432284.txt`

如果裝置每次都覆蓋同一路徑，那它只是 **latest copy**，不是 history。

---

## Layer 2. Snapshot/archive layer

負責把 landing file 變成不可變的歷史快照。

### Required outputs

每次接到新 backup 後，建立：

1. **latest copy**
2. **immutable archive copy**
3. **metadata record**

### Suggested directory layout

```text
/ha-emostore/
  inbox/
    7432284.txt
  latest/
    7432284.txt
  archive/
    7432284/
      2026-04-10T16-43-00+08-00.txt
      2026-04-10T18-10-24+08-00.txt
  metadata/
    7432284/
      2026-04-10T16-43-00+08-00.json
      2026-04-10T18-10-24+08-00.json
  normalized/
    7432284/
      2026-04-10T16-43-00+08-00.norm.txt
```

### Metadata should capture

至少應記：

- serial number / device identifier
- host name (if known)
- source path
- received time
- file size
- sha256
- source IP / FTP username if available
- parser version
- bound HA device id (if known)

---

## Layer 3. Versioning/diff layer

這層才是「版本控制」的核心。

### What it does

- compare latest snapshot with previous snapshot
- generate structured diff summary
- classify change type
- commit raw snapshots + metadata + normalized view to Git

### Why both raw and normalized views matter

**Raw file** 用於：
- true restore source
- forensic review
- source-of-truth preservation

**Normalized file** 用於：
- stable diff
- human review
- reducing formatting noise

### Example classification

- no-op / identical backup
- config drift
- credential changed
- network changed
- control/output config changed
- deploy-related config changed
- suspicious destructive change

---

## Layer 4. HA / `ha-unircon` overlay layer

這層不要自己當版本庫，而是當操作面。

### Good responsibilities here

- show latest snapshot time
- show latest snapshot hash
- show previous vs current diff summary
- show "config changed / unchanged"
- let operator trigger backup
- let operator compare two versions
- let operator request restore workflow
- write audit trail for operator actions

### Not the job of this layer

- storing the only copy of version history
- being the raw backup repository
- pretending recorder/history is enough for config versioning

---

## Recommended data flow

```text
EMOS device
  -> FTP upload to HA host
    -> inbox watcher
      -> copy to latest/
      -> archive immutable snapshot
      -> calculate sha256 + metadata
      -> normalize text for diff
      -> compare with previous snapshot
      -> write diff summary
      -> Git commit (or external version store)
      -> fire HA event / update `ha-unircon` overlay state
```

---

## Minimal viable implementation

如果先做最小可用版，我建議這樣分三步。

### Phase 1. Snapshot preservation

先做到：

- FTP 收件
- 每次變更存 timestamp archive
- 寫 metadata
- 保留 latest + archive

這一階段先不要急著做 restore。

### Phase 2. Diff + Git

再加：

- normalized render
- previous/current diff summary
- auto commit to Git
- commit message include device id + change summary

### Phase 3. `ha-unircon` integration

最後再把結果接回 HA：

- snapshot status sensor / event
- inventory overlay fields
- compare UI
- controlled restore workflow
- approval gate before restore

---

## Git strategy

如果 backup 是文字型 config，Git 很適合。

### What to commit

建議 commit：

- raw snapshot files
- metadata JSON
- normalized text
- diff summary

### Suggested commit message

```text
backup(7432284): snapshot 2026-04-10T16:43:00+08:00

host: Relay-685D
sha256: <hash>
change: wifi + mqtt unchanged
result: identical snapshot
```

### Important rule

不要只 commit `latest/7432284.txt`。

應該 commit archive snapshot，否則歷史會被覆蓋掉，看不到完整演進。

---

## Restore / rollback philosophy

這裡要很小心。

### Correct mindset

版本控制 ≠ 自動安全回滾。

因為 EMOS config restore 還牽涉：

- upload path semantics
- startup vs running differences
- write / reload behavior
- device-specific drift
- version/firmware compatibility

所以 restore workflow 應該設計成：

- **operator-approved controlled restore**
- not blind automatic rollback

### Recommended restore stages

1. pick snapshot
2. show diff against current
3. require explicit approval
4. send restore action
5. verify post-restore state
6. archive post-restore result as a new snapshot

---

## Where HA add-ons fit

如果 HA 主機已經裝了 add-ons / containers，這個架構非常容易落地。

### Useful services on the same HA host

- Mosquitto / EMQX: MQTT plane
- FTP server: backup ingest
- Filebrowser / Samba: manual inspection
- Node-RED / n8n: watcher / workflow / notification
- MariaDB / InfluxDB / other DB: optional metadata or analytics store

### Best role split

- **FTP**: receive files
- **watcher/workflow**: archive, diff, commit
- **Git repo**: authoritative history
- **HA / `ha-unircon`**: operator UI and policy gate

---

## Guardrails

### 1. Never overwrite the only copy

Landing file can be overwritten.
Archive snapshot must not.

### 2. Always keep raw file

不要只存解析後欄位。
真正 restore 或稽核時，raw 最重要。

### 3. Treat secrets carefully

Config 可能含：

- Wi-Fi credentials
- MQTT credentials
- admin credentials

所以 Git repo 若含 raw backups，預設應視為 **private ops repository**。

### 4. Do not assume every backup means a meaningful config change

有些 backup 只是重送同一份檔案。
要靠 hash + diff 分辨：

- identical
- semantically changed
- formatting-only changed

### 5. Separate backup from deploy source of truth

`deploy.txt` generation and config backup archive are related but not identical.

- backup archive = what device actually had
- deploy source = what operator intends to apply

兩者都要保留，不能混為一談。

---

## Recommended next steps for `ha-unircon`

### Near-term

1. 增加 backup snapshot metadata model
2. inventory export 加入 snapshot fields
3. 設計 HA event schema for new backup received
4. 設計 binding from serial/host to HA device registry

### Mid-term

1. compare snapshot UI
2. diff summary sensor/event
3. restore request workflow with approval gate
4. bind deploy workflow and backup history together

### Long-term

1. policy-aware rollback engine
2. multi-site backup repository
3. external backend integration for governance

---

## Concrete decision taken on 2026-04-10

對 EMOS 而言：

- **把 FTP backup server 放在 HA 同機器上，是合理且推薦的做法**
- 但 **FTP 本身不是版本控制**
- 版本控制應由 **snapshot archive + metadata + diff + Git** 這條鏈完成
- `ha-unircon` 應做成這條鏈的 **操作與可視化入口**，不是取代版本庫本身
