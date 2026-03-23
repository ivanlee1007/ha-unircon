/**
 * UNiNUS Console Card v2
 * Phase 2: Direct MQTT WebSocket streaming
 * Phase 3: Deploy config generator
 * Phase 4: Batch command processing UI
 * Phase 5: URCON neighbor discovery + auto-add
 */
class UNiNUSConsoleCard extends HTMLElement {
  setConfig(config) {
    this.config = { title: "UNiNUS Console", ...config };
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._init();
      this._render();
    }
  }
  getCardSize() { return 20; }

  _init() {
    this._initialized = true;
    this._terminalLines = [];
    this._statusLines = [];
    this._commandHistory = [];
    this._historyIdx = -1;
    this._selectedHost = "";
    this._token = "";
    this._tab = "console";
    this._mqtt = null;
    this._connected = false;
    this._batchRunning = false;
    this._neighbors = [];
    this._cmdQueue = [];
    this._waitingReply = false;
    // Restore broker settings from localStorage
    try {
      const s = localStorage.getItem("unircon_broker");
      if (s) this._broker = JSON.parse(s);
    } catch(_) {}
    this._broker = this._broker || {
      host: (this.config.broker && this.config.broker.host) || "",
      port: (this.config.broker && this.config.broker.port) || 1884,
      username: (this.config.broker && this.config.broker.username) || "",
      password: (this.config.broker && this.config.broker.password) || "",
      domain: (this.config.broker && this.config.broker.domain) || "uninus",
      hostName: (this.config.broker && this.config.broker.hostName) || "ha-card",
      path: (this.config.broker && this.config.broker.path) || "",
    };
    // Deploy form defaults
    this._deploy = {
      backup_protocol: "ftp", backup_server: "192.168.1.222", backup_file: "share/^sn^.txt",
      update_protocol: "mqtt", update_server: "192.168.1.222", update_port: "1883",
      update_user: "admin", update_password: "uninus@99",
      update_subscribe: "^ha_prefix^/sub/^hostname^", update_publish: "^ha_prefix^/pub/^hostname^",
      update_publish_response: "^ha_prefix^/pubrsp/^hostname^", update_publish_log: "^ha_prefix^/log/^hostname^",
      sta_ssid: "", sta_password: "",
      ntp_server: "118.163.81.62", ntp_timezone: "8",
    };
    // Subscribe to HA events for console updates from integration
    if (this._hass) {
      this._hass.connection.subscribeEvents((ev) => {
        const d = ev.data || {};
        const payload = d.data || {};
        const nested = payload && typeof payload.data === "object" ? payload.data : {};
        const eventType = payload.type ?? d.type;
        const eventHost = payload.host || d.host;
        const eventIp = payload.ip || d.ip || "";
        const isDiscovery = d.kind === "urcon_discovery" || eventType === 13 || eventType === 14;
        const isSelfDiscovery = isDiscovery && Number(eventType) === 13 && eventHost === "urcon";

        if (isDiscovery && eventHost && !isSelfDiscovery) {
          if (!this._neighbors.includes(eventHost)) {
            this._neighbors.push(eventHost);
          }
        }

        const token = payload.token || nested.token || "";
        if (token) {
          this._token = token;
        }

        const rawOutput = payload.output || nested.output || "";
        // Route: [bracket] lines + "-->" command echo → status; rest → terminal
        const isStatusLine = rawOutput.startsWith("[") || rawOutput.startsWith("-->");
        const terminalLine = rawOutput && !isStatusLine ? rawOutput : "";
        let statusLine = isStatusLine && rawOutput ? rawOutput : "";
        if (!terminalLine && !statusLine && token) {
          statusLine = `Token[${payload.deviceid || nested.deviceid || eventHost || "?"}]: ${token}`;
        }
        if (!terminalLine && !statusLine && isDiscovery && eventHost && !isSelfDiscovery) {
          statusLine = `[URCON] Discovered neighbor: ${eventHost} (${eventIp}) [src=${d.source || "event"}, type=${eventType}]`;
        }
        if (!terminalLine && !statusLine && payload.raw) {
          statusLine = String(payload.raw);
        }
        if (!terminalLine && !statusLine && !isSelfDiscovery && (payload.topic || d.topic)) {
          statusLine = `[MQTT] ${payload.topic || d.topic}`;
        }

        if (terminalLine) this._pushTerminal(terminalLine);
        if (statusLine) this._pushStatus(statusLine);
        this._render();
      }, "unircon_console");
    }
  }

  _pushTerminal(line) {
    if (!line) return;
    const str = String(line);
    this._terminalLines.unshift(str);
    if (this._terminalLines.length > 500) this._terminalLines.pop();
    // Sequential command queue: detect device response (non-echo line while waiting)
    if (!str.startsWith("-->") && this._waitingReply) {
      this._onDeviceResponse();
    }
  }

  _pushStatus(line) {
    if (!line) return;
    this._statusLines.unshift(String(line));
    if (this._statusLines.length > 500) this._statusLines.pop();
  }

  // ===== MQTT WebSocket (Phase 2) =====
  _readBrokerInputs() {
    const q = (id, fallback = "") => {
      const el = this.querySelector(id);
      return el ? el.value : fallback;
    };
    return {
      ...this._broker,
      host: q("#ms-host", this._broker.host || "").trim(),
      port: parseInt(q("#ms-port", this._broker.port || 1884), 10) || 1884,
      username: q("#ms-user", this._broker.username || ""),
      password: q("#ms-pass", this._broker.password || ""),
      domain: q("#ms-domain", this._broker.domain || "uninus").trim() || "uninus",
    };
  }

  _persistBrokerSettings(showMessage = true) {
    this._broker = this._readBrokerInputs();
    if (!this._broker.host) {
      this._pushStatus("[ERROR] MQTT broker host is empty");
      return false;
    }
    try {
      localStorage.setItem("unircon_broker", JSON.stringify(this._broker));
      if (showMessage) this._pushStatus(`[MQTT] Settings saved (${this._broker.host}:${this._broker.port})`);
      return true;
    } catch (e) {
      this._pushStatus(`[ERROR] Failed to save MQTT settings: ${e.message}`);
      return false;
    }
  }

  _setupWsSocketHandlers(ws, b, url, remainingUrls) {
    let opened = false;
    this._mqtt = ws;
    this._wsFrameSeq = this._wsFrameSeq || 0;

    ws.onopen = () => {
      opened = true;
      this._connected = true;
      this._pushStatus(`[MQTT] Connected to ${url}`);
      const hosts = this.config.hosts || [];
      const discoveryHost = (b.hostName || "urcon").trim() || "urcon";
      const topics = new Set([
        "ha/pub/+/console/#",
        "ha/pubrsp/#",
        `urcom/${(b.domain || "uninus").trim() || "uninus"}`,
        `ha/sub/${discoveryHost}`,
        "ha/sub/urcon",
      ]);
      hosts.forEach(h => {
        topics.add(`ha/pub/${h}/console/#`);
        topics.add(`ha/pubrsp/${h}/#`);
      });
      const subscribeAll = (phase) => {
        if (this._mqtt !== ws || !this._connected) return;
        topics.forEach(topic => ws.send(JSON.stringify({ cmd: "sub", topic })));
        this._pushStatus(`[MQTT] Subscribed${phase ? ` (${phase})` : ""}: ${Array.from(topics).join(", ")}`);
        this._render();
      };
      if (b.username) {
        ws.send(JSON.stringify({
          cmd: "auth", username: b.username, password: b.password, client_id: "ha-card-" + Math.random().toString(36).substr(6)
        }));
      }
      subscribeAll("initial");
      setTimeout(() => subscribeAll("retry-500ms"), 500);
      setTimeout(() => subscribeAll("retry-1500ms"), 1500);
    };

    ws.onmessage = (evt) => {
      const raw = typeof evt.data === "string" ? evt.data : String(evt.data);
      const debugWindow = this._debugRawWsUntil && Date.now() < this._debugRawWsUntil;
      const debugSeq = ++this._wsFrameSeq;
      if (debugWindow) {
        this._pushStatus(`[WS#${debugSeq}] ${raw.substring(0, 500)}`);
      }
      try {
        const msg = JSON.parse(raw);
        let payload = msg;
        if (typeof msg.payload === "string") {
          try {
            payload = JSON.parse(msg.payload);
          } catch (_) {
            payload = { raw: msg.payload, topic: msg.topic };
          }
        } else if (msg.data && typeof msg.data === "object") {
          payload = msg.data;
        }

        const nested = payload && typeof payload.data === "object" ? payload.data : {};
        const token = (payload && payload.token) || nested.token || "";
        const output = (payload && payload.output) || nested.output || "";
        if (output) {
          this._pushTerminal(output);
        } else if (token) {
          this._pushStatus(`Token[${payload.deviceid || nested.deviceid || payload.host || "?"}]: ${token}`);
          this._token = token;
        } else if (payload && (payload.type === 13 || payload.type === 14) && payload.host) {
          this._pushStatus(`[URCON] Raw discovery: ${JSON.stringify(payload)}`);
        } else if (!debugWindow) {
          this._pushStatus(raw.substring(0, 500));
        }
        if (payload && payload.host && (payload.type === 13 || payload.type === 14)) {
          const name = payload.host;
          if (!this._neighbors.includes(name)) {
            this._neighbors.push(name);
            this._pushStatus(`[URCON] Discovered neighbor: ${name} (${payload.ip || ""})`);
          }
        }
      } catch(_) {
        if (!debugWindow) this._pushStatus(raw.substring(0, 500));
      }
      this._render();
    };

    ws.onclose = () => {
      this._connected = false;
      if (!opened && remainingUrls.length) {
        const nextUrl = remainingUrls.shift();
        this._pushStatus(`[MQTT] WS connect failed, trying ${nextUrl}`);
        this._tryMqttUrls(b, [nextUrl, ...remainingUrls]);
        return;
      }
      this._pushStatus("[MQTT] Disconnected");
      this._render();
    };

    ws.onerror = () => {
      this._connected = false;
      if (!opened) return;
      this._pushStatus("[MQTT] Connection error - check broker address/port");
      this._render();
    };
  }

  _tryMqttUrls(b, urls) {
    if (!urls.length) {
      this._pushStatus("[ERROR] MQTT WebSocket connect failed for all candidate URLs");
      this._render();
      return;
    }
    const [url, ...remainingUrls] = urls;
    try {
      const ws = new WebSocket(url);
      this._setupWsSocketHandlers(ws, b, url, remainingUrls);
    } catch (e) {
      if (remainingUrls.length) {
        this._tryMqttUrls(b, remainingUrls);
      } else {
        this._pushStatus(`[MQTT] Error: ${e.message}`);
        this._render();
      }
    }
  }

  _mqttConnect() {
    const saved = this._persistBrokerSettings(false);
    const b = this._broker;
    if (!b.host) {
      this._pushStatus("[ERROR] MQTT broker host not configured");
      this._render();
      return;
    }
    try { if (this._mqtt) this._mqtt.close(); } catch(_) {}
    const candidates = [];
    const path = (b.path || "").trim();
    if (path) {
      candidates.push(`ws://${b.host}:${b.port}${path.startsWith("/") ? path : "/" + path}`);
    }
    candidates.push(`ws://${b.host}:${b.port}`);
    candidates.push(`ws://${b.host}:${b.port}/mqtt`);
    const deduped = [...new Set(candidates)];
    if (saved) this._pushStatus(`[MQTT] Using broker ${b.host}:${b.port}`);
    this._tryMqttUrls(b, deduped);
  }

  _mqttDisconnect() {
    try { if (this._mqtt) this._mqtt.close(); } catch(_) {}
    this._mqtt = null;
    this._connected = false;
  }

  _mqttSend(topic, payload) {
    if (this._connected && this._mqtt) {
      // Use HA service (more reliable) if MQTT WS not connected
      this._hass.callService("unircon", "mqtt_publish", { topic, payload }).catch(() => {});
    } else {
      this._hass.callService("unircon", "mqtt_publish", { topic, payload }).catch(() => {});
    }
  }

  // ===== Actions =====
  _sendCmd() {
    const inp = this.querySelector("#uc-cmd");
    if (!inp || !inp.value.trim()) return;
    const lines = inp.value.split("\n").map(l => l.trim()).filter(l => l);
    if (lines.length === 0) return;
    const host = this._selectedHost || (this.config.hosts && this.config.hosts[0]) || "";
    // Add all lines to history
    this._commandHistory.push(...lines);
    this._historyIdx = this._commandHistory.length;
    // Queue commands for sequential execution
    lines.forEach(cmd => this._cmdQueue.push({ host, cmd }));
    inp.value = "";
    this._processCmdQueue();
    this._updateCmdButton();
  }
  _processCmdQueue() {
    if (this._waitingReply || this._cmdQueue.length === 0) return;
    const { host, cmd } = this._cmdQueue.shift();
    this._waitingReply = true;
    this._pushTerminal(`--> ${cmd}`);
    this._hass.callService("unircon", "send_command", { host, command: cmd, token: this._token }).catch(() => {});
    this._updateCmdButton();
  }
  _onCmdEcho(line) {
    // Original echo format: '--[cmd]--' or '--> cmd'
    if (this._waitingReply) return; // already tracking
    // This is an echo from hotkey/batch, not from _processCmdQueue
    // Nothing to do - these are fire-and-forget
  }
  _onDeviceResponse() {
    if (this._waitingReply) {
      this._waitingReply = false;
      this._processCmdQueue();
    }
  }
  _updateCmdButton() {
    const btn = this.querySelector("#uc-send");
    if (!btn) return;
    if (this._cmdQueue.length > 0 || this._waitingReply) {
      btn.textContent = `▶ ${this._cmdQueue.length} 等待中`;
      btn.style.opacity = "0.7";
    } else {
      btn.textContent = "▶ 執行";
      btn.style.opacity = "1";
    }
  }
  _hotkey(cmd) {
    const host = this._selectedHost || (this.config.hosts && this.config.hosts[0]) || "";
    this._pushTerminal(`--> ${cmd}`);
    this._hass.callService("unircon", "send_command", { host, command: cmd, token: this._token }).catch(() => {});
  }
  _downloadOutput() {
    const text = this._terminalLines.join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `console_${this._selectedHost || "output"}_${new Date().toISOString().slice(0,10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }
  _clearOutput() {
    this._terminalLines = [];
    this._render();
  }
  _reqToken() {
    const host = this._selectedHost || (this.config.hosts && this.config.hosts[0]) || "";
    this._hass.callService("unircon", "request_token", { host }).catch(() => {});
    this._pushStatus("--> Requesting token...");
  }

  // ===== Deploy config (Phase 3) =====
  _genDeploy() {
    const d = this._deploy;
    const lines = [];
    lines.push(`backup protocol ${d.backup_protocol}`);
    lines.push(`  server ${d.backup_server}`);
    lines.push(`  file ${d.backup_file}`);
    lines.push("!");
    lines.push(`update protocol ${d.update_protocol}`);
    lines.push(`  server ${d.update_server} ${d.update_port}`);
    lines.push(`  user ${d.update_user} ${d.update_password}`);
    lines.push(`  subscribe ${d.update_subscribe}`);
    lines.push(`  publish ${d.update_publish}`);
    lines.push(`  publish response ${d.update_publish_response}`);
    lines.push(`  publish log ${d.update_publish_log}`);
    lines.push("!");
    if (d.sta_ssid) {
      lines.push("interface sta");
      lines.push("  ip dhcp");
      lines.push(`  sta ssid ${d.sta_ssid}`);
      lines.push(`  sta password ${d.sta_password}`);
      lines.push("!");
    }
    lines.push(`ntp server ${d.ntp_server}`);
    lines.push(`ntp timezone ${d.ntp_timezone}`);
    lines.push("!");
    return lines.join("\n");
  }
  _copyDeploy() {
    const text = this._genDeploy();
    navigator.clipboard.writeText(text).then(() => {
      this._pushStatus("[Deploy] 已複製到剪貼簿");
      this._render();
    }).catch(() => {});
  }
  _downloadDeploy() {
    const text = this._genDeploy();
    const blob = new Blob([text], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "deploy.txt";
    a.click();
  }
  _fillDeploy(field, value) {
    this._deploy[field] = value;
  }

  // ===== Batch (Phase 4) =====
  async _runBatch() {
    if (this._batchRunning) return;
    const hostEl = this.querySelector("#uc-batch-hosts");
    const cmdEl = this.querySelector("#uc-batch-cmds");
    if (!hostEl || !cmdEl) return;
    const hosts = hostEl.value.split(/\r?\n+/).map(s => s.trim()).filter(Boolean);
    const cmds = cmdEl.value.split(/\r?\n+/).map(s => s.trim()).filter(Boolean);
    if (!hosts.length || !cmds.length) { this._pushStatus("[Batch] 主機清單或指令為空"); this._render(); return; }
    this._batchRunning = true;
    this._pushStatus(`[Batch] 開始：${hosts.length} 台主機 × ${cmds.length} 條指令`);
    this._render();
    for (const host of hosts) {
      this._pushStatus(`[Batch] === ${host} ===`);
      this._render();
      // Request token
      this._hass.callService("unircon", "request_token", { host }).catch(() => {});
      await new Promise(r => setTimeout(r, 2000));
      for (const cmd of cmds) {
        this._pushTerminal(`[${host}] --> ${cmd}`);
        this._hass.callService("unircon", "send_command", { host, command: cmd }).catch(() => {});
        this._render();
        await new Promise(r => setTimeout(r, 1500));
      }
      this._pushStatus(`[Batch] ${host} 完成`);
      this._render();
    }
    this._batchRunning = false;
    this._pushStatus("[Batch] 全部完成");
    this._render();
  }

  // ===== Neighbors (Phase 5) =====
  _collectNeighbors() {
    const browserCallbackIp = (window.__localIP || (location && location.hostname) || "").trim();
    const broker = this._readBrokerInputs();
    const serviceData = {
      discovery_host_name: "urcon",
      callback_ip: browserCallbackIp,
      urcon_domain: (broker.domain || "uninus").trim() || "uninus",
    };
    this._debugRawWsUntil = Date.now() + 20000;
    this._wsFrameSeq = 0;
    this._neighbors = [];
    this._hass.callService("unircon", "collect_neighbors", serviceData).catch(() => {});
    this._pushStatus(`--> Searching for UNiNUS neighbors... callback=${serviceData.callback_ip || "(auto)"}`);
    this._pushStatus("[INFO] Discovery display now follows backend MQTT events first; WS raw capture stays enabled for 20s as debug only");
    this._render();
  }
  _addNeighbor(host) {
    if (!this.config.hosts) this.config.hosts = [];
    if (!this.config.hosts.includes(host)) {
      this.config.hosts.push(host);
      this._hass.callService("unircon", "add_device", { host }).catch(() => {});
      this._pushStatus(`[URCON] Added ${host} to host list`);
      this._render();
    }
  }

  _addAllNeighbors() {
    if (!this.config.hosts) this.config.hosts = [];
    const pending = this._neighbors.filter((host) => !this.config.hosts.includes(host));
    if (!pending.length) {
      this._pushStatus("[URCON] 沒有新的鄰居可加入");
      this._render();
      return;
    }
    this.config.hosts.push(...pending);
    pending.forEach((host) => this._hass.callService("unircon", "add_device", { host }).catch(() => {}));
    this._pushStatus(`[URCON] Added ${pending.length} neighbors to host list: ${pending.join(", ")}`);
    this._render();
  }

  // ===== Rendering =====
  _E(v) { return String(v??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

  _render() {
    const hosts = this.config.hosts || [];
    const sel = this._selectedHost || hosts[0] || "";
    const terminalLines = this._terminalLines.slice(-150).join("\n");
    const statusLines = this._statusLines.slice(-150).join("\n");
    const connColor = this._connected ? "#4caf50" : "#f44336";
    const connLabel = this._connected ? "已連線" : "未連線";
    const buildVersion = "1.0.40";

    this.innerHTML = `
    <style>
      ha-card{overflow:hidden}
      .uh{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-bottom:1px solid var(--divider-color,#e0e0e0)}
      .uh h2{margin:0;font-size:17px;font-weight:600}
      .utag{padding:2px 8px;border-radius:999px;background:rgba(33,150,243,.12);color:var(--primary-color,#03a9f4);font-size:.7rem;font-weight:700}
      .utt{display:flex;gap:2px;padding:6px 10px;border-bottom:1px solid var(--divider-color,#eee)}
      .utt button{padding:5px 12px;font-size:12.5px;border:1px solid var(--divider-color,#ccc);border-bottom:none;background:var(--card-background,#f5f5f5);cursor:pointer;border-radius:4px 4px 0 0}
      .utt button:hover{background:#e8e8e8}
      .utt button.on{background:var(--card-background,#fff);border-bottom:1px solid var(--card-background,#fff);font-weight:700;color:var(--primary-color,#03a9f4)}
      .tp{display:none;padding:8px 12px}
      .tp.on{display:block}
      .ubar{display:flex;flex-wrap:wrap;gap:5px;padding:6px 10px;align-items:center}
      .ubar select,.ubar input{padding:3px 6px;font-size:12.5px;border:1px solid var(--divider-color,#ccc);border-radius:4px}
      .ubar button{padding:3px 10px;font-size:12px;background:var(--primary-color,#03a9f4);color:#fff;border:none;border-radius:4px;cursor:pointer}
      .ubar button:hover{opacity:.85}
      .ubar button.red{background:#d9534f}
      .ubar button.green{background:#4caf50}
      .ubar .dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px}
      .ubar .spacer{flex:1}
      .uhk{display:flex;gap:3px;padding:4px 10px;flex-wrap:wrap}
      .uhk button{padding:2px 7px;font-size:11.5px;border:1px solid var(--divider-color,#ccc);background:var(--card-background,#fafafa);cursor:pointer;border-radius:3px}
      .uhk button:hover{background:var(--primary-color,#03a9f4);color:#fff}
      .ucns{margin:6px 10px}
      .ucblk{margin-bottom:8px}
      .uclbl{font-size:12px;font-weight:700;color:var(--secondary-text-color,#666);margin:0 0 4px 0;display:flex;align-items:center;gap:4px}
      .ucns textarea{width:100%;font-family:monospace;font-size:12.5px;padding:8px;border-radius:5px;resize:vertical;box-sizing:border-box}
      #uc-out{height:440px;background:#1e1e1e;color:#d4d4d4}
      #uc-stat{height:120px;background:#111827;color:#cbd5e1;border:1px solid rgba(148,163,184,.25)}
      .ucnr{display:flex;gap:5px;margin-top:5px}
      .ucnr input{flex:1;padding:5px 8px;font-family:monospace;font-size:12.5px;border:1px solid var(--divider-color,#ccc);border-radius:4px}
      .ucnr button{padding:5px 12px;background:var(--primary-color,#03a9f4);color:#fff;border:none;border-radius:4px;cursor:pointer}
      /* Phase 3: Deploy */
      .dpf{padding:4px 0}
      .dpf .row{margin:4px 0;display:flex;align-items:center;gap:8px;line-height:1.4}
      .dpf .row label{font-size:13px;color:var(--secondary-text-color,#666);min-width:110px}
      .dpf .row input,.dpf .row select{height:26px;padding:3px 6px;font-size:13px;border:1px solid var(--divider-color,#ccc);border-radius:4px}
      .dpf .row input[type=text]{flex:1}
      .dpf hr{margin:6px 0;border:none;border-top:1px dashed var(--divider-color,#ddd)}
      .dpf .actions{margin-top:8px;display:flex;gap:6px}
      .dpf textarea.deploy-out{width:100%;height:200px;font-family:monospace;font-size:12px;margin-top:8px;border:1px solid var(--divider-color,#ccc);border-radius:4px;resize:vertical;box-sizing:border-box}
      /* Phase 4: Batch */
      .bat{display:grid;grid-template-columns:1fr 1fr;gap:8px}
      .bat textarea{height:140px;font-family:monospace;font-size:12.5px;padding:6px;border:1px solid var(--divider-color,#ccc);border-radius:4px;resize:vertical;box-sizing:border-box}
      .bat label{font-size:13px;margin-bottom:2px;display:block}
      /* Phase 5: Neighbors */
      .nblist{margin-top:8px}
      .nblist .nb{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:13px}
      .nblist .nb button{padding:2px 8px;font-size:11px;background:var(--primary-color,#03a9f4);color:#fff;border:none;border-radius:3px;cursor:pointer}
      /* MQTT settings */
      .msf .row{margin:5px 0;display:flex;align-items:center;gap:8px}
      .msf .row label{font-size:13px;min-width:100px;color:var(--secondary-text-color,#666)}
      .msf .row input{height:26px;padding:3px 6px;font-size:13px;border:1px solid var(--divider-color,#ccc);border-radius:4px;flex:1}
    </style>
    <ha-card header="${this._E(`${this.config.title||"UNiNUS Console"} v${buildVersion}`)}">
      <div class="uh">
        <span style="font-size:13px">${this._E(sel||"未選擇")} · <span style="color:${connColor}">${connLabel}</span></span>
        <span class="utag">build v${this._E(buildVersion)}</span>
      </div>

      <!-- Tabs -->
      <div class="utt">
        <button class="${this._tab==='console'?'on':''}" data-tab="console">🖥️ 主控台</button>
        <button class="${this._tab==='deploy'?'on':''}" data-tab="deploy">📋 部署檔</button>
        <button class="${this._tab==='batch'?'on':''}" data-tab="batch">📦 批次處理</button>
        <button class="${this._tab==='mqtt'?'on':''}" data-tab="mqtt">📡 MQTT</button>
      </div>

      <!-- Tab: Console (Phase 1+) -->
      <div class="tp ${this._tab==='console'?'on':''}" id="tp-console">
        <div class="ubar">
          <select id="uc-host">${hosts.map(h=>`<option value="${this._E(h)}" ${h===sel?"selected":""}>${this._E(h)}</option>`).join("")}</select>
          <button id="uc-tok">要求序號</button>
          <span class="spacer"></span>
          <input id="uc-tokin" placeholder="Token" value="${this._E(this._token)}" style="width:110px"/>
        </div>
        <div class="uhk">
          <button data-cmd="en admin uninus@99">Enable</button>
          <button data-cmd="sh ver">show ver</button>
          <button data-cmd="sh urcon/ne">urcon/ne</button>
          <button data-cmd="sh result">result</button>
          <button data-cmd="show run">show run</button>
        </div>
        <div class="ucns">
          <div style="display:flex;gap:8px">
            <div class="ucblk" style="flex:1;min-width:0">
              <div class="uclbl">
                <span>訊息輸出 (Console Output)</span>
                <span style="margin-left:auto;display:flex;gap:4px">
                  <button id="uc-dl-out" title="下載輸出">📥</button>
                  <button id="uc-clr-out" title="清除輸出">🗑️</button>
                </span>
              </div>
              <textarea id="uc-out" readonly style="height:440px">${this._E(terminalLines)}</textarea>
            </div>
            <div class="ucblk" style="flex:0 0 220px;display:flex;flex-direction:column">
              <div class="uclbl">指令輸入</div>
              <textarea id="uc-cmd" placeholder="每行一個指令&#10;Ctrl+Enter 送出&#10;Alt+↑↓ 歷史" style="flex:1;min-height:120px;font-family:monospace;font-size:12px;background:rgba(255,255,255,.08);color:inherit;border:1px solid var(--divider-color,#555);border-radius:3px;padding:4px;resize:vertical"></textarea>
              <div style="display:flex;gap:8px;margin-top:6px">
                <button id="uc-send" style="flex:1">▶ 執行</button>
                <button id="uc-clr-cmd" style="flex:0;background:var(--error-color,#d9534f)">清空</button>
              </div>
            </div>
          </div>
          <div class="ucblk">
            <div class="uclbl">狀態訊息 (Stat Message)</div>
            <textarea id="uc-stat" readonly>${this._E(statusLines)}</textarea>
          </div>

        </div>
      </div>

      <!-- Tab: Deploy (Phase 3) -->
      <div class="tp ${this._tab==='deploy'?'on':''}" id="tp-deploy">
        <div class="dpf" id="deploy-form">
          <div class="row"><label>backup protocol</label><select id="dp-bp"><option value="ftp" selected>ftp</option><option value="http">http</option><option value="tftp">tftp</option></select></div>
          <div class="row"><label>&nbsp;&nbsp;server</label><input type="text" id="dp-bs" value="192.168.1.222"/></div>
          <div class="row"><label>&nbsp;&nbsp;file</label><input type="text" id="dp-bf" value="share/^sn^.txt"/></div>
          <hr/>
          <div class="row"><label>update protocol</label><select id="dp-up"><option value="mqtt" selected>mqtt</option><option value="http">http</option><option value="tcp">tcp</option></select></div>
          <div class="row"><label>&nbsp;&nbsp;server</label><input type="text" id="dp-us" value="192.168.1.222"/><input type="text" id="dp-upt" value="1883" style="width:70px"/></div>
          <div class="row"><label>&nbsp;&nbsp;user</label><input type="text" id="dp-uu" value="admin"/><input type="text" id="dp-upw" value="uninus@99"/></div>
          <div class="row"><label>&nbsp;&nbsp;subscribe</label><input type="text" id="dp-sub" value="^ha_prefix^/sub/^hostname^"/></div>
          <div class="row"><label>&nbsp;&nbsp;publish</label><input type="text" id="dp-pub" value="^ha_prefix^/pub/^hostname^"/></div>
          <div class="row"><label>&nbsp;&nbsp;pub response</label><input type="text" id="dp-pubr" value="^ha_prefix^/pubrsp/^hostname^"/></div>
          <div class="row"><label>&nbsp;&nbsp;pub log</label><input type="text" id="dp-publ" value="^ha_prefix^/log/^hostname^"/></div>
          <hr/>
          <div class="row"><label>sta ssid</label><input type="text" id="dp-ssid" placeholder="WiFi SSID"/></div>
          <div class="row"><label>sta password</label><input type="text" id="dp-spw" placeholder="WiFi Password"/></div>
          <hr/>
          <div class="row"><label>ntp server</label><input type="text" id="dp-ntp" value="118.163.81.62"/></div>
          <div class="row"><label>ntp timezone</label><input type="text" id="dp-tz" value="8" style="width:50px"/></div>
          <div class="actions">
            <button id="dp-gen">生成</button>
            <button id="dp-copy">複製</button>
            <button id="dp-dl" style="background:#0275d8">下載</button>
          </div>
          <textarea id="dp-out" class="deploy-out" readonly placeholder="點「生成」預覽..."></textarea>
        </div>
      </div>

      <!-- Tab: Batch (Phase 4) -->
      <div class="tp ${this._tab==='batch'?'on':''}" id="tp-batch">
        <div class="bat">
          <div><label>主機清單（每行一台）</label><textarea id="uc-batch-hosts" placeholder="sensor01&#10;sensor02&#10;sensor03">${hosts.join("\n")}</textarea></div>
          <div><label>批次指令（每行一條）</label><textarea id="uc-batch-cmds" placeholder="sh ver&#10;sh result&#10;show run">sh ver&#10;show run</textarea></div>
        </div>
        <div style="margin-top:8px;display:flex;gap:6px">
          <button id="uc-batch-run" style="background:#4caf50;color:#fff;border:none;padding:6px 14px;border-radius:4px;cursor:pointer">▶ 執行批次</button>
          <button id="uc-batch-clear" style="background:#d9534f;color:#fff;border:none;padding:6px 14px;border-radius:4px;cursor:pointer">清空</button>
        </div>
        <div id="uc-batch-status" style="margin-top:6px;font-size:12px;color:var(--secondary-text-color,#888)"></div>
      </div>

      <!-- Tab: MQTT (Phase 5) -->
      <div class="tp ${this._tab==='mqtt'?'on':''}" id="tp-mqtt">
        <div class="msf">
          <div class="row"><label>Broker</label><input id="ms-host" value="${this._E(this._broker.host)}" placeholder="192.168.1.222"/></div>
          <div class="row"><label>WebSocket Port</label><input id="ms-port" value="${this._E(this._broker.port)}" placeholder="1884" style="width:80px"/></div>
          <div class="row"><label>Username</label><input id="ms-user" value="${this._E(this._broker.username)}"/></div>
          <div class="row"><label>Password</label><input id="ms-pass" type="password" value="${this._E(this._broker.password)}"/></div>
          <div class="row"><label>URCON Domain</label><input id="ms-domain" value="${this._E(this._broker.domain)}" style="width:120px"/></div>
          <div style="margin:6px 0;display:flex;gap:6px">
            <button id="ms-save" style="padding:5px 12px;background:var(--primary-color,#03a9f4);color:#fff;border:none;border-radius:4px;cursor:pointer">💾 儲存設定</button>
            <button id="ms-connect" style="padding:5px 12px;background:#4caf50;color:#fff;border:none;border-radius:4px;cursor:pointer">🔗 連線</button>
            <button id="ms-disconnect" style="padding:5px 12px;background:#d9534f;color:#fff;border:none;border-radius:4px;cursor:pointer">斷開</button>
          </div>
        </div>
        <hr style="border:none;border-top:1px dashed var(--divider-color,#ddd);margin:8px 0"/>
        <div style="display:flex;gap:6px;align-items:center">
          <label style="font-size:13px">MQTT 測試發佈：</label>
          <input id="ms-topic" placeholder="ha/test/topic" style="flex:1;padding:3px 6px;border:1px solid var(--divider-color,#ccc);border-radius:4px"/>
          <input id="ms-payload" placeholder='{"msg":"hello"}' style="flex:1;padding:3px 6px;border:1px solid var(--divider-color,#ccc);border-radius:4px"/>
          <button id="ms-pub" style="padding:4px 10px;background:var(--primary-color,#03a9f4);color:#fff;border:none;border-radius:4px;cursor:pointer">Publish</button>
        </div>
        <hr style="border:none;border-top:1px dashed var(--divider-color,#ddd);margin:8px 0"/>
        <div>
          <button id="ms-neighbor" style="padding:5px 12px;background:#ff9800;color:#fff;border:none;border-radius:4px;cursor:pointer">🔍 蒐集 UNiNUS 鄰居</button>
          <button id="ms-add-all-nb" style="padding:5px 10px;background:#4caf50;color:#fff;border:none;border-radius:4px;cursor:pointer;margin-left:4px">加入全部鄰居</button>
          <button id="ms-clear-nb" style="padding:5px 10px;background:var(--secondary-text-color,#888);color:#fff;border:none;border-radius:4px;cursor:pointer;margin-left:4px">清除列表</button>
        </div>
        <div class="nblist" id="nb-list">
          ${this._neighbors.map(n => `<div class="nb">📡 ${n} <button data-add="${this._E(n)}">加入主機清單</button></div>`).join("")}
          ${this._neighbors.length === 0 ? '<div style="font-size:12px;color:#888;margin-top:4px">尚未探索，點擊上方按鈕開始</div>' : ''}
        </div>
      </div>

    </ha-card>`;

    // ===== Event bindings =====
    // Tabs
    this.querySelectorAll(".utt button").forEach(b => {
      b.addEventListener("click", () => { this._tab = b.dataset.tab; this._render(); });
    });
    // Console
    const ta = this.querySelector("#uc-out");
    if (ta) ta.scrollTop = ta.scrollHeight;
    const ts = this.querySelector("#uc-stat");
    if (ts) ts.scrollTop = ts.scrollHeight;
    const hs = this.querySelector("#uc-host");
    if (hs) hs.addEventListener("change", e => { this._selectedHost = e.target.value; });
    const ti = this.querySelector("#uc-tokin");
    if (ti) ti.addEventListener("change", e => { this._token = e.target.value; });
    const sb = this.querySelector("#uc-send");
    if (sb) sb.addEventListener("click", () => this._sendCmd());
    const dlOut = this.querySelector("#uc-dl-out");
    if (dlOut) dlOut.addEventListener("click", () => this._downloadOutput());
    const clrOut = this.querySelector("#uc-clr-out");
    if (clrOut) clrOut.addEventListener("click", () => this._clearOutput());
    const ci = this.querySelector("#uc-cmd");
    if (ci) {
      ci.addEventListener("keydown", e => {
        if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); this._sendCmd(); }
        if (e.key === "ArrowUp" && e.altKey && this._commandHistory.length) { e.preventDefault(); this._historyIdx = Math.max(0, this._historyIdx - 1); ci.value = this._commandHistory[this._historyIdx] || ""; }
        if (e.key === "ArrowDown" && e.altKey) { e.preventDefault(); this._historyIdx = Math.min(this._commandHistory.length, this._historyIdx + 1); ci.value = this._commandHistory[this._historyIdx] || ""; }
      });
    }
    const clrCmd = this.querySelector("#uc-clr-cmd");
    if (clrCmd) clrCmd.addEventListener("click", () => { const i = this.querySelector("#uc-cmd"); if (i) i.value = ""; this._cmdQueue = []; this._waitingReply = false; this._updateCmdButton(); this._pushStatus("指令輸入已清空"); });
    this.querySelectorAll(".uhk button").forEach(b => {
      b.addEventListener("click", () => this._hotkey(b.dataset.cmd));
    });
    const tb = this.querySelector("#uc-tok");
    if (tb) tb.addEventListener("click", () => this._reqToken());

    // Deploy (Phase 3)
    const dpGen = this.querySelector("#dp-gen");
    if (dpGen) dpGen.addEventListener("click", () => {
      // Read form values
      this._deploy.backup_protocol = this.querySelector("#dp-bp").value;
      this._deploy.backup_server = this.querySelector("#dp-bs").value;
      this._deploy.backup_file = this.querySelector("#dp-bf").value;
      this._deploy.update_protocol = this.querySelector("#dp-up").value;
      this._deploy.update_server = this.querySelector("#dp-us").value;
      this._deploy.update_port = this.querySelector("#dp-upt").value;
      this._deploy.update_user = this.querySelector("#dp-uu").value;
      this._deploy.update_password = this.querySelector("#dp-upw").value;
      this._deploy.update_subscribe = this.querySelector("#dp-sub").value;
      this._deploy.update_publish = this.querySelector("#dp-pub").value;
      this._deploy.update_publish_response = this.querySelector("#dp-pubr").value;
      this._deploy.update_publish_log = this.querySelector("#dp-publ").value;
      this._deploy.sta_ssid = this.querySelector("#dp-ssid").value;
      this._deploy.sta_password = this.querySelector("#dp-spw").value;
      this._deploy.ntp_server = this.querySelector("#dp-ntp").value;
      this._deploy.ntp_timezone = this.querySelector("#dp-tz").value;
      this.querySelector("#dp-out").value = this._genDeploy();
    });
    const dpCp = this.querySelector("#dp-copy");
    if (dpCp) dpCp.addEventListener("click", () => this._copyDeploy());
    const dpDl = this.querySelector("#dp-dl");
    if (dpDl) dpDl.addEventListener("click", () => this._downloadDeploy());

    // Batch (Phase 4)
    const br = this.querySelector("#uc-batch-run");
    if (br) br.addEventListener("click", () => this._runBatch());
    const bc = this.querySelector("#uc-batch-clear");
    if (bc) bc.addEventListener("click", () => {
      const h = this.querySelector("#uc-batch-hosts"); if (h) h.value = "";
      const c = this.querySelector("#uc-batch-cmds"); if (c) c.value = "";
    });

    // MQTT settings (Phase 5)
    const bindBrokerField = (selector, key, parser = (v) => v) => {
      const el = this.querySelector(selector);
      if (!el) return;
      const update = () => {
        this._broker[key] = parser(el.value);
      };
      el.addEventListener("input", update);
      el.addEventListener("change", update);
    };
    bindBrokerField("#ms-host", "host", (v) => (v || "").trim());
    bindBrokerField("#ms-port", "port", (v) => parseInt(v, 10) || 1884);
    bindBrokerField("#ms-user", "username");
    bindBrokerField("#ms-pass", "password");
    bindBrokerField("#ms-domain", "domain", (v) => (v || "").trim() || "uninus");

    const msSave = this.querySelector("#ms-save");
    if (msSave) msSave.addEventListener("click", () => {
      this._persistBrokerSettings(true);
      this._render();
    });
    const msConn = this.querySelector("#ms-connect");
    if (msConn) msConn.addEventListener("click", () => this._mqttConnect());
    const msDisc = this.querySelector("#ms-disconnect");
    if (msDisc) msDisc.addEventListener("click", () => this._mqttDisconnect());
    const msPub = this.querySelector("#ms-pub");
    if (msPub) msPub.addEventListener("click", () => {
      const t = this.querySelector("#ms-topic").value;
      const p = this.querySelector("#ms-payload").value;
      this._mqttSend(t, p);
    });
    const msNb = this.querySelector("#ms-neighbor");
    if (msNb) msNb.addEventListener("click", () => this._collectNeighbors());
    const msAddAllNb = this.querySelector("#ms-add-all-nb");
    if (msAddAllNb) msAddAllNb.addEventListener("click", () => this._addAllNeighbors());
    const msClearNb = this.querySelector("#ms-clear-nb");
    if (msClearNb) msClearNb.addEventListener("click", () => { this._neighbors = []; this._render(); });
    // Add neighbor buttons
    this.querySelectorAll(".nblist button[data-add]").forEach(b => {
      b.addEventListener("click", () => this._addNeighbor(b.dataset.add));
    });
  }
}

if (!customElements.get("unircon-console-card")) {
  customElements.define("unircon-console-card", UNiNUSConsoleCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "custom:unircon-console-card")) {
  window.customCards.push({
    type: "custom:unircon-console-card",
    name: "UNiNUS Remote Console Card",
    description: "UNiNUS MQTT remote console dashboard card (bundled with ha-unircon)",
  });
}
