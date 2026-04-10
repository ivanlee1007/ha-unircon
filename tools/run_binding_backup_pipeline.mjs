#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { access, stat } from 'node:fs/promises';
import process from 'node:process';

function log(message) {
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] ${message}`);
}

function parseArgs(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      result[key] = 'true';
      continue;
    }
    result[key] = next;
    i += 1;
  }
  return result;
}

function readFlag(args, argName, envName, defaultValue = false) {
  const raw = args[argName] ?? process.env[envName];
  if (raw == null) return defaultValue;
  return ['1', 'true', 'yes', 'on'].includes(String(raw).trim().toLowerCase());
}

function readValue(args, argName, envName, defaultValue = '') {
  return args[argName] ?? process.env[envName] ?? defaultValue;
}

function parseHosts(raw) {
  if (!raw) return [];
  return String(raw)
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

async function callHaService({ haUrl, token, domain, service, data }) {
  const response = await fetch(`${haUrl}/api/services/${domain}/${service}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data ?? {}),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HA service ${domain}.${service} failed (${response.status}): ${text}`);
  }

  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function waitForFile(path, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start <= timeoutMs) {
    try {
      await access(path);
      const info = await stat(path);
      if (info.size >= 0) {
        return info;
      }
    } catch {
      // ignore until timeout
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Timed out waiting for file: ${path}`);
}

async function runWrapper({ repoRoot, env }) {
  await new Promise((resolve, reject) => {
    const child = spawn('bash', ['tools/run_emos_backup_scan.sh'], {
      cwd: repoRoot,
      stdio: 'inherit',
      env: {
        ...process.env,
        ...env,
      },
    });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`backup wrapper exited with code ${code}`));
      }
    });
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = readValue(args, 'repo-root', 'PIPELINE_REPO_ROOT', process.cwd());
  const haUrlRaw = readValue(args, 'ha-url', 'HA_URL', '');
  const token = readValue(args, 'ha-token', 'HA_TOKEN', '');
  const hosts = parseHosts(readValue(args, 'hosts', 'PIPELINE_HOSTS', ''));
  const bindingMapPath = readValue(
    args,
    'binding-map-path',
    'PIPELINE_BINDING_MAP_PATH',
    '/config/unircon/binding-map.generated.json',
  );
  const bindingMapServicePath = readValue(
    args,
    'binding-map-service-path',
    'PIPELINE_BINDING_MAP_SERVICE_PATH',
    'unircon/binding-map.generated.json',
  );
  const metadataRoot = readValue(
    args,
    'metadata-root',
    'PIPELINE_METADATA_ROOT',
    '/share/emostore/repo/metadata',
  );
  const healthWaitSeconds = Number(
    readValue(args, 'health-wait-seconds', 'PIPELINE_HEALTH_WAIT_SECONDS', '15'),
  );
  const fileWaitSeconds = Number(
    readValue(args, 'file-wait-seconds', 'PIPELINE_FILE_WAIT_SECONDS', '20'),
  );
  const skipHealthCheck = readFlag(args, 'skip-health-check', 'PIPELINE_SKIP_HEALTH_CHECK', false);
  const overwriteBindingMap = readFlag(args, 'overwrite-binding-map', 'PIPELINE_OVERWRITE_BINDING_MAP', true);
  const skipBackupStatusSync = readFlag(args, 'skip-backup-status-sync', 'PIPELINE_SKIP_BACKUP_STATUS_SYNC', false);
  const dryRun = readFlag(args, 'dry-run', 'PIPELINE_DRY_RUN', false);

  if (!haUrlRaw || !token) {
    throw new Error('HA_URL and HA_TOKEN are required');
  }

  const haUrl = haUrlRaw.replace(/\/$/, '');
  const serviceHosts = hosts.length ? { hosts } : {};
  const startedAt = new Date().toISOString();

  log(`pipeline start repo=${repoRoot}`);
  log(`ha=${haUrl} binding_map=${bindingMapPath} dry_run=${dryRun ? '1' : '0'}`);

  if (!skipHealthCheck) {
    log('calling HA service unircon.run_health_check');
    await callHaService({
      haUrl,
      token,
      domain: 'unircon',
      service: 'run_health_check',
      data: serviceHosts,
    });
    if (healthWaitSeconds > 0) {
      log(`waiting ${healthWaitSeconds}s for health-check replies`);
      await new Promise((resolve) => setTimeout(resolve, healthWaitSeconds * 1000));
    }
  } else {
    log('skip health check');
  }

  log('calling HA service unircon.save_binding_map');
  await callHaService({
    haUrl,
    token,
    domain: 'unircon',
    service: 'save_binding_map',
    data: {
      ...serviceHosts,
      path: bindingMapServicePath,
      overwrite: overwriteBindingMap,
    },
  });

  if (!dryRun) {
    log(`waiting for binding map file ${bindingMapPath}`);
    const info = await waitForFile(bindingMapPath, fileWaitSeconds * 1000);
    log(`binding map ready size=${info.size}`);
  } else {
    log('pipeline dry-run enabled, skip file wait and wrapper execution');
    console.log(
      JSON.stringify(
        {
          ok: true,
          started_at: startedAt,
          finished_at: new Date().toISOString(),
          dry_run: true,
          binding_map_path: bindingMapPath,
          hosts,
        },
        null,
        2,
      ),
    );
    return;
  }

  log('running backup wrapper');
  await runWrapper({
    repoRoot,
    env: {
      EMOS_BACKUP_BINDING_MAP: bindingMapPath,
    },
  });

  if (!skipBackupStatusSync) {
    log('calling HA service unircon.sync_backup_status');
    await callHaService({
      haUrl,
      token,
      domain: 'unircon',
      service: 'sync_backup_status',
      data: {
        ...serviceHosts,
        metadata_root: metadataRoot,
      },
    });
  } else {
    log('skip backup status sync');
  }

  console.log(
    JSON.stringify(
      {
        ok: true,
        started_at: startedAt,
        finished_at: new Date().toISOString(),
        binding_map_path: bindingMapPath,
        metadata_root: metadataRoot,
        hosts,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error?.stack || String(error));
  process.exit(1);
});
