// Check real Renovate JSONL extraction and the selected version's rule engine.
// Usage: node renovate/check-extraction.mjs <JSONL log> <tool node_modules>
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const [log, modules] = process.argv.slice(2);
assert(log && modules, 'Provide extraction log and tool node_modules paths');
const require = createRequire(path.resolve(modules, 'renovate/package.json'));
const config = require('json5').parse(fs.readFileSync('renovate.json5', 'utf8'));
const {applyPackageRules} = await import(pathToFileURL(path.resolve(modules,
  'renovate/dist/util/package-rules/index.js')));
const events = fs.readFileSync(log, 'utf8').split('\n').filter(Boolean).map(JSON.parse);
const event = events.find(e => e.msg === 'Extracted dependencies');
assert(event, 'Extraction did not finish');
// Explicit global config plus local repository config can duplicate regex records.
const records = new Map();
const rows = [];
for (const [manager, files] of Object.entries(event.packageFiles)) {
  for (const file of files) for (const dep of file.deps) {
    const row = {manager, packageFile: file.packageFile, ...dep};
    if (manager === 'regex') records.set(JSON.stringify(row), row);
    else rows.push(row);
  }
}
rows.push(...records.values());
function find(file, name, digest = true) {
  const matches = rows.filter(r => r.packageFile === file && r.depName === name);
  assert(matches.length, `Missing ${file}: ${name}`);
  if (digest) assert(matches.some(r => /^sha256:[a-f0-9]{64}$/.test(r.currentDigest)),
    `Missing digest: ${file}: ${name}`);
  return matches;
}
find('gerrit/statefulset.yaml', 'docker.io/gerritcodereview/gerrit');
find('gerrit/statefulset.yaml', 'docker.io/nginxinc/nginx-unprivileged');
find('herdr/deployment.yaml', 'ghcr.io/benkim0414/hermes-herdr');
find('hindsight/values.yaml', 'ghcr.io/vectorize-io/hindsight-control-plane');
find('langfuse/values.yaml', 'docker.langfuse.com/langfuse/langfuse');
find('langfuse/values.yaml', 'docker.langfuse.com/langfuse/langfuse-worker');
find('langfuse/values.yaml', 'postgres');
find('langfuse/values.yaml', 'docker.io/valkey/valkey');
find('langfuse/clickhouse.yaml', 'clickhouse/clickhouse-server');
assert.equal(find('langfuse/objectstore.yaml', 'chrislusf/seaweedfs').length, 2,
  'SeaweedFS server and initialization hook must both be extracted');
find('monitoring/loki-values.yaml', 'docker.io/grafana/loki');
for (const file of ['hermes/deployment.yaml', 'hermes/browser.yaml', 'hermes/backup-cronjob.yaml',
  'openclaw/deployment.yaml', 'openclaw/backup-cronjob.yaml', 'hindsight/api.yaml',
  'hindsight/pg-backup-cronjob.yaml']) {
  assert(rows.some(r => r.packageFile === file && r.datasource === 'docker' && r.currentDigest),
    `Missing runtime/backup digest: ${file}`);
}
find('k3s-ansible/inventory.yml', 'k3s-io/k3s', false);
find('immich/pg-backup-cronjob.yaml', 'ghcr.io/immich-app/postgres', false);
find('vaultwarden/backup-cronjob.yaml', 'python', false);
const effective = [];
for (const row of rows) effective.push(await applyPackageRules({...row,
  packageRules: config.packageRules}, 'verification'));
function policy(file, name) {
  const row = effective.find(r => r.packageFile === file && r.depName === name);
  assert(row, `Missing policy target ${file}: ${name}`);
  return row;
}
assert.equal(config.automerge, false);
assert.equal(config.ignoreUnstable, true);
assert.equal(policy('herdr/deployment.yaml', 'ghcr.io/benkim0414/hermes-herdr').enabled, false);
assert.equal(policy('argocd/apps/monitoring.yaml', 'loki').enabled, false);
assert.equal(policy('immich/postgresql.yaml', 'ghcr.io/immich-app/postgres').enabled, false);
for (const [file, name, allowed, denied] of [
  ['gerrit/statefulset.yaml', 'docker.io/gerritcodereview/gerrit', '3.14.7', '3.15.0'],
  ['gerrit/statefulset.yaml', 'docker.io/nginxinc/nginx-unprivileged', '1.28.3-alpine', '1.28.3-bookworm'],
  ['langfuse/values.yaml', 'postgres', '18.1', '19'],
  ['langfuse/values.yaml', 'docker.io/valkey/valkey', '8.0.6', '9.0'],
  ['langfuse/clickhouse.yaml', 'clickhouse/clickhouse-server', '26.8.37.1', '26.9.1.1'],
  ['hindsight/pg-backup-cronjob.yaml', 'pgvector/pgvector', '0.8.2-pg17-bookworm', '0.8.2-pg18-bookworm'],
  ['immich/pg-backup-cronjob.yaml', 'ghcr.io/immich-app/postgres',
    '16-vectorchord0.4.3-pgvectors0.2.0', '17-vectorchord0.4.3-pgvectors0.2.0'],
]) {
  const rule = policy(file, name);
  assert(rule.allowedVersions, `Constraint not applied: ${name}`);
  const re = new RegExp(rule.allowedVersions.slice(1, -1));
  assert(re.test(allowed) && !re.test(denied), `Constraint failed: ${name}`);
}
assert.equal(policy('langfuse/values.yaml', 'docker.langfuse.com/langfuse/langfuse-worker').groupName, 'langfuse');
assert.equal(policy('langfuse/values.yaml', 'postgres').groupName, 'langfuse-postgresql');
console.log(`Extraction and rule assertions passed (${rows.length} dependency records, duplicate regex extraction removed).`);
