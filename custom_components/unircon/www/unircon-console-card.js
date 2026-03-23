/**
 * UNiNUS Console Card
 * A Lovelace custom card for interactive UNiNUS device management.
 *
 * Usage:
 *   type: custom:unircon-console-card
 *   device: sensor.unircon_sensor01_console
 *   broker:
 *     host: 192.168.1.222
 *     port: 1884
 *     username: admin
 *     password: uninus@99
 *   hosts:
 *     - sensor01
 *     - sensor02
 */

class UNiNUSConsoleCard extends HTMLElement {
  setConfig(config) {
    this.config = {
      title: "UNiNUS Console",
      days: 7,
      ...config,
    };
  }

  set hass(hass) {
    this._hass = hass;
    this._ensureInitialized();
    this.render();
  }

  getCardSize() {
    return 15;
  }

  _ensureInitialized() {
    if (this._initialized) return;
    this._initialized = true;
    this._consoleLines = [];
    this._commandHistory = [];
    this._historyIndex = -1;
    this._selectedHost = "";
    this._token = "";
    this._connected = false;

    // Subscribe to HA events for console updates
    if (this._hass) {
      this._hass.connection.subscribeEvents((event) => {
        const data = event.data || {};
        if (data.data && data.data.output) {
          this._consoleLines.push(data.data.output);
        } else {
          this._consoleLines.push(JSON.stringify(data));
        }
        if (this._consoleLines.length > 300) this._consoleLines.shift();
        this.render();
      }, "unircon_console");
    }
  }

  _esc(v) {
    return String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  _sendCommand() {
    const input = this.querySelector("#cmd-input");
    if (!input || !input.value.trim()) return;
    const cmd = input.value.trim();
    this._commandHistory.push(cmd);
    this._historyIndex = this._commandHistory.length;
    this._consoleLines.push(`--> ${cmd}`);

    this._hass.callService("unircon", "send_command", {
      host: this._selectedHost || (this.config.hosts && this.config.hosts[0]) || "",
      command: cmd,
      token: this._token,
    }).catch(() => {});

    input.value = "";
    this.render();
  }

  _hotkey(cmd) {
    this._consoleLines.push(`--> ${cmd}`);
    this._hass.callService("unircon", "send_command", {
      host: this._selectedHost || (this.config.hosts && this.config.hosts[0]) || "",
      command: cmd,
      token: this._token,
    }).catch(() => {});
  }

  _requestToken() {
    this._hass.callService("unircon", "request_token", {
      host: this._selectedHost || (this.config.hosts && this.config.hosts[0]) || "",
    }).catch(() => {});
    this._consoleLines.push("--> Requesting token...");
  }

  _collectNeighbors() {
    this._hass.callService("unircon", "collect_neighbors", {}).catch(() => {});
    this._consoleLines.push("--> Collecting URCOM neighbors...");
  }

  render() {
    const a = {};
    // Try to read sensor state for token
    if (this.config.device && this._hass) {
      const st = this._hass.states[this.config.device];
      if (st) {
        a.token = st.attributes?.token || st.state || "";
      }
    }
    if (a.token && a.token !== "等待指令...") this._token = a.token;

    const hosts = this.config.hosts || [];
    const selectedHost = this._selectedHost || hosts[0] || "";
    const lines = this._consoleLines.slice(-100).join("\n");
    const buildTag = "v1.0 · unircon";

    this.innerHTML = `
      <style>
        ha-card { overflow: hidden; }
        .uc-header { display:flex; justify-content:space-between; align-items:center; padding:12px 16px; border-bottom:1px solid var(--divider-color, #e0e0e0); }
        .uc-header h2 { margin:0; font-size:18px; font-weight:600; }
        .uc-tag { padding:2px 8px; border-radius:999px; background:rgba(33,150,243,0.12); color:var(--primary-color, #03a9f4); font-size:.72rem; font-weight:700; }
        .uc-toolbar { display:flex; flex-wrap:wrap; gap:6px; padding:8px 12px; align-items:center; }
        .uc-toolbar select, .uc-toolbar input, .uc-toolbar button { padding:4px 8px; font-size:13px; border-radius:4px; border:1px solid var(--divider-color, #ccc); }
        .uc-toolbar button { cursor:pointer; background:var(--primary-color, #03a9f4); color:#fff; border:none; }
        .uc-toolbar button:hover { opacity:.85; }
        .uc-hotkeys { display:flex; gap:4px; padding:4px 12px; flex-wrap:wrap; }
        .uc-hotkeys button { padding:3px 8px; font-size:12px; border-radius:4px; border:1px solid var(--divider-color, #ccc); background:var(--card-background, #fafafa); cursor:pointer; }
        .uc-hotkeys button:hover { background:var(--primary-color, #03a9f4); color:#fff; }
        .uc-console { margin:8px 12px; }
        .uc-console textarea { width:100%; height:280px; font-family:monospace; font-size:13px; background:var(--primary-text-color, #212121); color:#00ff88; padding:10px; border-radius:6px; resize:vertical; box-sizing:border-box; }
        .uc-input-row { display:flex; gap:6px; margin-top:6px; }
        .uc-input-row input { flex:1; padding:6px 10px; font-family:monospace; font-size:13px; border-radius:4px; border:1px solid var(--divider-color, #ccc); }
        .uc-input-row button { padding:6px 14px; background:var(--primary-color, #03a9f4); color:#fff; border:none; border-radius:4px; cursor:pointer; white-space:nowrap; }
      </style>
      <ha-card header="${this._esc(this.config.title || "UNiNUS Console")}">
        <div class="uc-header">
          <span style="font-size:14px;">${this._esc(selectedHost || "未選擇")}</span>
          <span class="uc-tag">${buildTag}</span>
        </div>
        <div class="uc-toolbar">
          <select id="host-select">
            ${hosts.map(h => `<option value="${this._esc(h)}" ${h === selectedHost ? "selected" : ""}>${this._esc(h)}</option>`).join("")}
          </select>
          <button id="btn-token">要求序號</button>
          <button id="btn-neighbors">鄰居探索</button>
          <input id="token-input" placeholder="Token" value="${this._esc(this._token)}" style="width:120px;" />
        </div>
        <div class="uc-hotkeys">
          <button data-cmd="en admin uninus@99">Enable</button>
          <button data-cmd="sh ver">show version</button>
          <button data-cmd="sh urcon/ne">sh urcon/ne</button>
          <button data-cmd="sh result">sh result</button>
          <button data-cmd="backup">Backup</button>
        </div>
        <div class="uc-console">
          <textarea id="console-out" readonly>${this._esc(lines)}</textarea>
          <div class="uc-input-row">
            <input id="cmd-input" placeholder="輸入指令 (Ctrl+Enter 送出)" />
            <button id="btn-send">執行</button>
          </div>
        </div>
      </ha-card>
    `;

    // Auto-scroll console
    const ta = this.querySelector("#console-out");
    if (ta) ta.scrollTop = ta.scrollHeight;

    // Host select
    const hostSel = this.querySelector("#host-select");
    if (hostSel) {
      hostSel.addEventListener("change", (e) => {
        this._selectedHost = e.target.value;
        this.render();
      });
    }

    // Token input
    const tokenIn = this.querySelector("#token-input");
    if (tokenIn) {
      tokenIn.addEventListener("change", (e) => { this._token = e.target.value; });
    }

    // Send button
    const sendBtn = this.querySelector("#btn-send");
    if (sendBtn) sendBtn.addEventListener("click", () => this._sendCommand());

    // Command input
    const cmdIn = this.querySelector("#cmd-input");
    if (cmdIn) {
      cmdIn.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); this._sendCommand(); }
        if (e.key === "ArrowUp" && this._commandHistory.length) {
          this._historyIndex = Math.max(0, this._historyIndex - 1);
          cmdIn.value = this._commandHistory[this._historyIndex] || "";
        }
        if (e.key === "ArrowDown") {
          this._historyIndex = Math.min(this._commandHistory.length, this._historyIndex + 1);
          cmdIn.value = this._commandHistory[this._historyIndex] || "";
        }
      });
    }

    // Hot keys
    this.querySelectorAll(".uc-hotkeys button").forEach((btn) => {
      btn.addEventListener("click", () => this._hotkey(btn.dataset.cmd));
    });

    // Token request
    const tokenBtn = this.querySelector("#btn-token");
    if (tokenBtn) tokenBtn.addEventListener("click", () => this._requestToken());

    // Neighbors
    const nbBtn = this.querySelector("#btn-neighbors");
    if (nbBtn) nbBtn.addEventListener("click", () => this._collectNeighbors());
  }
}

customElements.define("unircon-console-card", UNiNUSConsoleCard);
