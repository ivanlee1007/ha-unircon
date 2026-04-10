#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

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

function nowIsoWithOffset(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  const padMs = (n) => String(n).padStart(3, '0');
  const y = date.getFullYear();
  const m = pad(date.getMonth() + 1);
  const d = pad(date.getDate());
  const hh = pad(date.getHours());
  const mm = pad(date.getMinutes());
  const ss = pad(date.getSeconds());
  const ms = padMs(date.getMilliseconds());
  const offsetMin = -date.getTimezoneOffset();
  const sign = offsetMin >= 0 ? '+' : '-';
  const abs = Math.abs(offsetMin);
  const offH = pad(Math.floor(abs / 60));
  const offM = pad(abs % 60);
  return `${y}-${m}-${d}T${hh}:${mm}:${ss}.${ms}${sign}${offH}:${offM}`;
}

function toFileSafeTimestamp(iso) {
  return iso.replace(/:/g, '-');
}

function sha256(content) {
  return createHash('sha256').update(content).digest('hex');
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function readTextIfExists(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch {
    return null;
  }
}

function loadJsonIfExists(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {
    return null;
  }
}

function normalizeString(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function normalizeStringList(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => normalizeString(item)).filter(Boolean);
}

function resolveBindingRecord(serial, bindingMap) {
  const rawEntry = bindingMap?.[serial];
  const fallback = {
    serial,
    host: null,
    site: null,
    ha_device_id: null,
    mqtt_identifier: serial,
    base_entities: [],
    manufacturer: null,
    model: null,
    sw_version: null,
    notes: null,
    matched_on: null,
  };

  if (!rawEntry) return fallback;

  if (typeof rawEntry === 'string') {
    return {
      ...fallback,
      host: normalizeString(rawEntry),
      matched_on: 'serial',
    };
  }

  if (typeof rawEntry !== 'object' || Array.isArray(rawEntry)) {
    return fallback;
  }

  return {
    serial: normalizeString(rawEntry.serial) || serial,
    host: normalizeString(rawEntry.host) || normalizeString(rawEntry.hostname),
    site: normalizeString(rawEntry.site),
    ha_device_id: normalizeString(rawEntry.ha_device_id),
    mqtt_identifier:
      normalizeString(rawEntry.mqtt_identifier)
      || normalizeString(rawEntry.device_identifier)
      || serial,
    base_entities: normalizeStringList(rawEntry.base_entities || rawEntry.entities),
    manufacturer: normalizeString(rawEntry.manufacturer),
    model: normalizeString(rawEntry.model),
    sw_version: normalizeString(rawEntry.sw_version) || normalizeString(rawEntry.firmware),
    notes: normalizeString(rawEntry.notes),
    matched_on: 'serial',
  };
}

function saveJson(filePath, value) {
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2) + '\n', 'utf8');
}

function normalizeContent(text) {
  return text
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split('\n')
    .map((line) => line.replace(/[ \t]+$/g, ''))
    .join('\n')
    .trimEnd()
    .concat('\n');
}

function listSnapshotBaseNames(dirPath) {
  try {
    return fs.readdirSync(dirPath)
      .filter((name) => name.endsWith('.norm.txt'))
      .map((name) => name.slice(0, -'.norm.txt'.length))
      .sort();
  } catch {
    return [];
  }
}

function git(args, options = {}) {
  return spawnSync('git', args, {
    cwd: options.cwd,
    encoding: 'utf8',
    stdio: options.stdio || 'pipe',
  });
}

function ensureGitRepo(repoRoot) {
  if (fs.existsSync(path.join(repoRoot, '.git'))) return;
  const init = git(['init'], { cwd: repoRoot });
  if (init.status !== 0) {
    throw new Error(`git init failed: ${init.stderr || init.stdout}`);
  }
}

function relativeFrom(base, target) {
  return path.relative(base, target).split(path.sep).join('/');
}

function classifyChange(previousNormalized, currentNormalized, previousSha, currentSha) {
  if (!previousNormalized) return 'initial';
  if (previousSha === currentSha) return 'identical';

  const previous = previousNormalized.toLowerCase();
  const current = currentNormalized.toLowerCase();
  const changedText = `${previous}\n---\n${current}`;

  if (changedText.includes('ssid') || changedText.includes('wifi') || changedText.includes('ip ') || changedText.includes('dhcp')) {
    return 'network_changed';
  }
  if (changedText.includes('password') || changedText.includes('pass ') || changedText.includes('user ') || changedText.includes('mqtt')) {
    return 'credentials_changed';
  }
  if (changedText.includes('deploy') || changedText.includes('backup protocol') || changedText.includes('update protocol')) {
    return 'deploy_changed';
  }
  if (changedText.includes('ou ') || changedText.includes('relay') || changedText.includes('timer') || changedText.includes('auto ')) {
    return 'control_changed';
  }
  return 'unknown_changed';
}

function buildDiffSummary({ serial, binding, previousNormPath, currentNormPath, previousSha, currentSha, changeType, changed }) {
  const header = [
    `# Diff Summary for ${serial}`,
    '',
    `- host: ${binding.host || 'unknown'}`,
    `- site: ${binding.site || 'unknown'}`,
    `- ha_device_id: ${binding.ha_device_id || 'unbound'}`,
    `- mqtt_identifier: ${binding.mqtt_identifier || 'unknown'}`,
    `- base_entity_count: ${binding.base_entities.length}`,
    `- changed: ${changed}`,
    `- change_type: ${changeType}`,
    `- previous_sha256: ${previousSha || 'none'}`,
    `- current_sha256: ${currentSha}`,
    '',
  ];

  if (!previousNormPath) {
    return `${header.join('\n')}Initial snapshot, no previous version to compare.\n`;
  }

  if (!changed) {
    return `${header.join('\n')}No content change detected against previous snapshot.\n`;
  }

  const diff = git(['diff', '--no-index', '--', previousNormPath, currentNormPath]);
  const body = diff.stdout || diff.stderr || 'git diff produced no output.';
  return `${header.join('\n')}## Unified diff\n\n\`\`\`diff\n${body.trimEnd()}\n\`\`\`\n`;
}

function maybeCommit(repoRoot, serial, iso, host, changeType) {
  ensureGitRepo(repoRoot);
  git(['add', '.'], { cwd: repoRoot });
  const status = git(['status', '--short'], { cwd: repoRoot });
  if (!status.stdout.trim()) {
    return { committed: false, commit: null };
  }
  const message = `backup(${serial}): snapshot ${iso}`;
  const body = [`host: ${host || 'unknown'}`, `change: ${changeType}`].join('\n');
  const commit = git(['commit', '-m', message, '-m', body], { cwd: repoRoot });
  if (commit.status !== 0) {
    throw new Error(`git commit failed: ${commit.stderr || commit.stdout}`);
  }
  const rev = git(['rev-parse', 'HEAD'], { cwd: repoRoot });
  return { committed: true, commit: rev.stdout.trim() };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const root = path.resolve(args.root || process.env.EMOS_BACKUP_ROOT || '/share/emostore');
  const repoRoot = path.resolve(args.repo || process.env.EMOS_BACKUP_REPO || path.join(root, 'repo'));
  const inboxDir = path.join(root, 'inbox');
  const latestDir = path.join(root, 'latest');
  const archiveRoot = path.join(repoRoot, 'archive');
  const metadataRoot = path.join(repoRoot, 'metadata');
  const normalizedRoot = path.join(repoRoot, 'normalized');
  const diffsRoot = path.join(repoRoot, 'diffs');
  const runtimeRoot = path.join(root, 'runtime');
  const statePath = path.join(runtimeRoot, 'worker-state.json');
  const bindingMapPath = args['binding-map']
    || process.env.EMOS_BACKUP_BINDING_MAP
    || args['host-map']
    || process.env.EMOS_BACKUP_HOST_MAP
    || '';
  const doCommit = Boolean(args.commit || process.env.EMOS_BACKUP_COMMIT === '1');
  const dryRun = Boolean(args['dry-run']);

  [root, repoRoot, inboxDir, latestDir, archiveRoot, metadataRoot, normalizedRoot, diffsRoot, runtimeRoot].forEach(ensureDir);

  const bindingMap = bindingMapPath ? loadJsonIfExists(path.resolve(bindingMapPath)) || {} : {};
  const state = loadJsonIfExists(statePath) || { serials: {} };
  const files = fs.readdirSync(inboxDir)
    .filter((name) => name.endsWith('.txt'))
    .sort();

  const results = [];

  for (const fileName of files) {
    const serial = path.basename(fileName, '.txt');
    const inboxPath = path.join(inboxDir, fileName);
    const fileStat = fs.statSync(inboxPath);
    const rawContent = fs.readFileSync(inboxPath, 'utf8');
    const currentSha = sha256(rawContent);
    const previousState = state.serials[serial] || null;
    if (
      previousState
      && Number(previousState.mtime_ms) === Number(fileStat.mtimeMs)
      && Number(previousState.size) === Number(fileStat.size)
      && previousState.sha256 === currentSha
    ) {
      continue;
    }

    const normalized = normalizeContent(rawContent);
    const iso = nowIsoWithOffset();
    const timestamp = toFileSafeTimestamp(iso);
    const binding = resolveBindingRecord(serial, bindingMap);
    const host = binding.host;

    const latestPath = path.join(latestDir, `${serial}.txt`);
    const previousLatest = readTextIfExists(latestPath);
    const previousSha = previousLatest ? sha256(previousLatest) : null;
    const changed = previousSha !== currentSha;

    const archiveDir = path.join(archiveRoot, serial);
    const metadataDir = path.join(metadataRoot, serial);
    const normalizedDir = path.join(normalizedRoot, serial);
    const diffsDir = path.join(diffsRoot, serial);
    [archiveDir, metadataDir, normalizedDir, diffsDir].forEach(ensureDir);

    const previousSnapshots = listSnapshotBaseNames(normalizedDir);
    const previousBase = previousSnapshots.length ? previousSnapshots[previousSnapshots.length - 1] : null;
    const previousNormPath = previousBase ? path.join(normalizedDir, `${previousBase}.norm.txt`) : null;
    const previousNormalized = previousNormPath ? readTextIfExists(previousNormPath) : null;

    const archivePath = path.join(archiveDir, `${timestamp}.txt`);
    const normalizedPath = path.join(normalizedDir, `${timestamp}.norm.txt`);
    const diffPath = path.join(diffsDir, `${timestamp}.diff.md`);
    const metadataPath = path.join(metadataDir, `${timestamp}.json`);

    const changeType = classifyChange(previousNormalized, normalized, previousSha, currentSha);

    const metadata = {
      metadata_schema_version: 2,
      serial,
      host,
      site: binding.site,
      received_at: iso,
      source_path: inboxPath,
      archive_path: relativeFrom(repoRoot, archivePath),
      normalized_path: relativeFrom(repoRoot, normalizedPath),
      diff_path: relativeFrom(repoRoot, diffPath),
      size: Buffer.byteLength(rawContent, 'utf8'),
      sha256: currentSha,
      previous_sha256: previousSha,
      changed,
      change_type: changeType,
      binding_map_path: bindingMapPath ? path.resolve(bindingMapPath) : null,
      ha_device_id: binding.ha_device_id,
      mqtt_identifier: binding.mqtt_identifier,
      base_entities: binding.base_entities,
      device_identity: {
        manufacturer: binding.manufacturer,
        model: binding.model,
        sw_version: binding.sw_version,
      },
      binding: {
        matched_on: binding.matched_on,
        notes: binding.notes,
      },
      notes: ['starter worker pipeline', binding.notes].filter(Boolean),
    };

    if (!dryRun) {
      fs.writeFileSync(latestPath, rawContent, 'utf8');
      fs.writeFileSync(archivePath, rawContent, 'utf8');
      fs.writeFileSync(normalizedPath, normalized, 'utf8');
      const diffSummary = buildDiffSummary({
        serial,
        binding,
        previousNormPath,
        currentNormPath: normalizedPath,
        previousSha,
        currentSha,
        changeType,
        changed,
      });
      fs.writeFileSync(diffPath, diffSummary, 'utf8');
      saveJson(metadataPath, metadata);
      state.serials[serial] = {
        inbox_path: inboxPath,
        mtime_ms: fileStat.mtimeMs,
        size: fileStat.size,
        sha256: currentSha,
        last_processed_at: iso,
        latest_archive_path: relativeFrom(repoRoot, archivePath),
      };
    }

    results.push({
      serial,
      host,
      site: binding.site,
      haDeviceId: binding.ha_device_id,
      entityCount: binding.base_entities.length,
      changed,
      changeType,
      archivePath,
      metadataPath,
      normalizedPath,
      diffPath,
    });
  }

  if (!dryRun) {
    saveJson(statePath, state);
  }

  let commitInfo = null;
  if (!dryRun && doCommit && results.length) {
    const last = results[results.length - 1];
    const iso = nowIsoWithOffset();
    commitInfo = maybeCommit(repoRoot, last.serial, iso, last.host, last.changeType);
  }

  console.log(JSON.stringify({
    root,
    repoRoot,
    processed: results.length,
    dryRun,
    commit: commitInfo,
    results: results.map((item) => ({
      ...item,
      archivePath: relativeFrom(repoRoot, item.archivePath),
      metadataPath: relativeFrom(repoRoot, item.metadataPath),
      normalizedPath: relativeFrom(repoRoot, item.normalizedPath),
      diffPath: relativeFrom(repoRoot, item.diffPath),
    })),
  }, null, 2));
}

main();
