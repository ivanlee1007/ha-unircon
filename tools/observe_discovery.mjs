#!/usr/bin/env node
import mqtt from 'mqtt';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      out[key] = true;
      continue;
    }
    out[key] = next;
    i += 1;
  }
  return out;
}

function now() {
  return new Date().toISOString().replace('T', ' ').replace('Z', 'Z');
}

function log(channel, message) {
  console.log(`[${now()}] [${channel}] ${message}`);
}

const args = parseArgs(process.argv.slice(2));

const config = {
  host: args.host || process.env.UNIRCON_HOST || '192.168.1.222',
  wsPort: Number(args['ws-port'] || process.env.UNIRCON_WS_PORT || 1884),
  tcpPort: Number(args['tcp-port'] || process.env.UNIRCON_TCP_PORT || 1883),
  username: args.user || process.env.UNIRCON_USER || 'admin',
  password: args.password || process.env.UNIRCON_PASSWORD || 'uninus@99',
  domain: args.domain || process.env.UNIRCON_DOMAIN || 'uninus',
  discoveryHost: args['discovery-host'] || process.env.UNIRCON_DISCOVERY_HOST || 'urcon',
  callbackIp: args['callback-ip'] || process.env.UNIRCON_CALLBACK_IP || 'home.uninus.com.tw',
  settleMs: Number(args['settle-ms'] || process.env.UNIRCON_SETTLE_MS || 2500),
  observeMs: Number(args['observe-ms'] || process.env.UNIRCON_OBSERVE_MS || 8000),
  path: args.path || process.env.UNIRCON_WS_PATH || '',
};

const wsUrl = `ws://${config.host}:${config.wsPort}${config.path}`;
const tcpUrl = `mqtt://${config.host}:${config.tcpPort}`;
const wsClientId = `probe-ws-${Math.random().toString(36).slice(2, 10)}`;
const tcpClientId = `probe-tcp-${Math.random().toString(36).slice(2, 10)}`;

const topics = [
  'ha/pub/+/console/#',
  'ha/pubrsp/#',
  `urcom/${config.domain}`,
  `ha/sub/${config.discoveryHost}`,
  'ha/sub/urcon',
  'ha/sub/#',
];

const discoveryPayload = {
  host: config.discoveryHost,
  user: config.username,
  pass: config.password,
  plen: 0,
  type: 13,
  domain: config.domain,
  ip: config.callbackIp,
  rch: `ha/sub/${config.discoveryHost}`,
  payload: '',
};

const summary = {
  wsFrames: 0,
  wsType14: 0,
  wsTopics: new Set(),
  tcpMessages: 0,
  tcpType14: 0,
  tcpTopics: new Set(),
};

let tcpClient;
let ws;

async function setupTcp() {
  return new Promise((resolve, reject) => {
    tcpClient = mqtt.connect(tcpUrl, {
      username: config.username,
      password: config.password,
      clientId: tcpClientId,
      reconnectPeriod: 0,
      connectTimeout: 5000,
    });

    tcpClient.on('connect', () => {
      log('TCP', `connected to ${tcpUrl} as ${tcpClientId}`);
      tcpClient.subscribe(topics, { qos: 1 }, (err, granted) => {
        if (err) {
          reject(err);
          return;
        }
        log('TCP', `subscribed: ${granted.map((g) => `${g.topic}@${g.qos}`).join(', ')}`);
        resolve();
      });
    });

    tcpClient.on('message', (topic, payloadBuffer) => {
      const payloadText = payloadBuffer.toString('utf8');
      summary.tcpMessages += 1;
      summary.tcpTopics.add(topic);
      log('TCP-RX', `${topic} :: ${payloadText.slice(0, 500)}`);
      try {
        const data = JSON.parse(payloadText);
        if (data?.type === 14) summary.tcpType14 += 1;
      } catch {}
    });

    tcpClient.on('error', (err) => {
      reject(err);
    });
  });
}

async function setupWs() {
  return new Promise((resolve, reject) => {
    ws = new WebSocket(wsUrl);
    let opened = false;

    ws.addEventListener('open', () => {
      opened = true;
      log('WS', `connected to ${wsUrl} as ${wsClientId}`);
      ws.send(JSON.stringify({
        cmd: 'auth',
        username: config.username,
        password: config.password,
        client_id: wsClientId,
      }));
      const sendSubs = (phase) => {
        topics.forEach((topic) => ws.send(JSON.stringify({ cmd: 'sub', topic })));
        log('WS', `subscribed (${phase}): ${topics.join(', ')}`);
      };
      sendSubs('initial');
      setTimeout(() => sendSubs('retry-500ms'), 500);
      setTimeout(() => sendSubs('retry-1500ms'), 1500);
      resolve();
    });

    ws.addEventListener('message', (evt) => {
      const raw = typeof evt.data === 'string' ? evt.data : String(evt.data);
      summary.wsFrames += 1;
      log('WS-RX', raw.slice(0, 500));
      try {
        const msg = JSON.parse(raw);
        const topic = msg.topic || msg.data?.topic;
        if (topic) summary.wsTopics.add(topic);
        let payload = msg;
        if (typeof msg.payload === 'string') {
          try {
            payload = JSON.parse(msg.payload);
          } catch {}
        } else if (msg.data && typeof msg.data === 'object') {
          payload = msg.data;
        }
        if (payload?.type === 14) summary.wsType14 += 1;
      } catch {}
    });

    ws.addEventListener('error', (err) => {
      if (!opened) reject(err.error || new Error('WS connect error'));
      log('WS', 'error event emitted');
    });

    ws.addEventListener('close', (evt) => {
      log('WS', `closed code=${evt.code} reason=${evt.reason || '<empty>'}`);
    });
  });
}

async function main() {
  log('CFG', JSON.stringify({
    host: config.host,
    wsPort: config.wsPort,
    tcpPort: config.tcpPort,
    domain: config.domain,
    discoveryHost: config.discoveryHost,
    callbackIp: config.callbackIp,
    settleMs: config.settleMs,
    observeMs: config.observeMs,
  }));

  await setupTcp();
  await setupWs();
  await sleep(config.settleMs);

  const payloadText = JSON.stringify(discoveryPayload);
  log('TCP-TX', `publishing urcom/${config.domain} :: ${payloadText}`);
  tcpClient.publish(`urcom/${config.domain}`, payloadText, { qos: 0, retain: false });

  await sleep(config.observeMs);

  log('SUMMARY', JSON.stringify({
    wsFrames: summary.wsFrames,
    wsType14: summary.wsType14,
    wsTopics: Array.from(summary.wsTopics),
    tcpMessages: summary.tcpMessages,
    tcpType14: summary.tcpType14,
    tcpTopics: Array.from(summary.tcpTopics),
  }, null, 2));

  if (ws && ws.readyState === WebSocket.OPEN) ws.close();
  if (tcpClient) tcpClient.end(true);
}

main().catch((err) => {
  console.error(`[${now()}] [FATAL]`, err?.stack || err);
  try { if (ws && ws.readyState === WebSocket.OPEN) ws.close(); } catch {}
  try { if (tcpClient) tcpClient.end(true); } catch {}
  process.exitCode = 1;
});
