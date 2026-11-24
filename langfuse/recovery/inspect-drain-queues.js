"use strict";
// Langfuse worker 4.77.0, pinned image 1bc3597f...; static source only.
// Never import @langfuse/shared, BullMQ Queue, Worker or application startup.
// BullMQ 5.76.3 getCounts Lua can RPOP legacy markers: DO NOT use its API.
const fs = require("fs"), path = require("path"), crypto = require("crypto");
const digest = x => crypto.createHash("sha256").update(x).digest("hex");
const TREES = [
  [882, "512594a1d7ecf650aa15b7364c41984ba05d99b3566d25207f30e421ac76272a"],
  [267, "4a1561fcdefc5dbd928535163416cb29fa64bb65b85bcbd2934857f1e6e02ca4"],
  [256, "d1529f2c9dc0d994a0899b3063bcd2102924fe0d30842f64136dfedf449cb13f"]
];
const SHARDS = {
  IngestionQueue: "LANGFUSE_INGESTION_QUEUE_SHARD_COUNT",
  IngestionSecondaryQueue: "LANGFUSE_INGESTION_SECONDARY_QUEUE_SHARD_COUNT",
  OtelIngestionQueue: "LANGFUSE_OTEL_INGESTION_QUEUE_SHARD_COUNT",
  OtelIngestionSecondaryQueue: "LANGFUSE_OTEL_INGESTION_SECONDARY_QUEUE_SHARD_COUNT",
  EvaluationExecution: "LANGFUSE_EVAL_EXECUTION_QUEUE_SHARD_COUNT",
  EvaluationExecutionSecondaryQueue: "LANGFUSE_EVAL_EXECUTION_SECONDARY_QUEUE_SHARD_COUNT",
  LLMAsJudgeExecution: "LANGFUSE_LLM_AS_JUDGE_EXECUTION_QUEUE_SHARD_COUNT",
  CodeEvalExecution: "LANGFUSE_CODE_EVAL_EXECUTION_QUEUE_SHARD_COUNT",
  TopicsTrace: "LANGFUSE_TOPICS_TRACE_QUEUE_SHARD_COUNT",
  TraceUpsert: "LANGFUSE_TRACE_UPSERT_QUEUE_SHARD_COUNT"
};
const STATES = {wait: "list", active: "list", delayed: "zset", prioritized: "zset",
  paused: "list", "waiting-children": "zset", repeat: "zset", stalled: "set",
  failed: "zset", completed: "zset"};
// Atomic per-queue observation; no values, IDs, members or errors leave Redis.
// repeat ZCARD includes both legacy repeatables AND modern job schedulers in
// this version (job-scheduler.js, repeat.js and scheduleRecurringJob.js).
// Count all delayed/repeat work: do not silently exempt future cron jobs.
// Lists include obsolete markers conservatively, without inspecting/removing.
const COUNT_LUA = `
local result = {}
for i = 1, #KEYS - 1 do
  local typ = redis.call('TYPE', KEYS[i]).ok
  local expected = ARGV[i]
  if typ ~= 'none' and typ ~= expected then return {-1} end
  local cmd = 'ZCARD'
  if expected == 'list' then cmd = 'LLEN' end
  if expected == 'set' then cmd = 'SCARD' end
  result[#result + 1] = redis.call(cmd, KEYS[i])
end
local typ = redis.call('TYPE', KEYS[#KEYS]).ok
if typ ~= 'none' and typ ~= 'hash' then return {-1} end
result[#result + 1] = redis.call('HEXISTS', KEYS[#KEYS], 'paused')
return result
`;
function fail() { throw new Error("drain-not-admitted"); }
function treeHash(root) {
  const files = [];
  function walk(d) {
    for (const e of fs.readdirSync(d, {withFileTypes: true})) {
      const f = path.join(d, e.name);
      if (e.isDirectory()) walk(f);
      else if (e.isFile() && /\.(js|lua)$/.test(f)) files.push(f);
      else if (e.isSymbolicLink()) fail();
    }
  }
  walk(root); files.sort();
  const h = crypto.createHash("sha256");
  for (const f of files) h.update(path.relative(root, f) + "\0" + digest(fs.readFileSync(f)) + "\n");
  return [files.length, h.digest("hex")];
}
function sourceRoots() {
  const resolve = n => require.resolve(n, {paths: ["/app/worker"]});
  const shared = path.dirname(resolve("@langfuse/shared"));
  const bull = path.dirname(resolve("bullmq/package.json"));
  if (JSON.parse(fs.readFileSync(path.join(bull, "package.json"))).version !== "5.76.3" ||
      JSON.parse(fs.readFileSync(resolve("ioredis/package.json"))).version !== "5.10.1") fail();
  const roots = [shared, "/app/worker/dist", path.join(bull, "dist/cjs")];
  roots.forEach((r, i) => { if (JSON.stringify(treeHash(r)) !== JSON.stringify(TREES[i])) fail(); });
  return shared;
}
function registry(source, env) {
  const block = source.match(/var QueueName;\s*\(function \(QueueName\) \{([\s\S]*?)\}\)\(QueueName/);
  if (!block) fail();
  const entries = [...block[1].matchAll(/QueueName\["([A-Za-z0-9]+)"\] = "([a-z0-9-]+)";/g)];
  if (entries.length !== 46 || new Set(entries.map(e => e[1])).size !== 46 ||
      new Set(entries.map(e => e[2])).size !== 46 ||
      block[1].replace(/QueueName\["([A-Za-z0-9]+)"\] = "([a-z0-9-]+)";/g, "").trim()) fail();
  if (digest(JSON.stringify(entries.map(e => [e[1], e[2]]))) !==
      "082dd35f9849f9869d48e7752f2f22f0311ffd35bfa62f8a19b3f8c8388b8ef6") fail();
  const names = [];
  for (const [, id, name] of entries) {
    const key = SHARDS[id];
    const raw = key ? (env[key] === undefined ? "1" : env[key]) : "1";
    if (!/^[1-9][0-9]*$/.test(raw) || Number(raw) > 64) fail();
    for (let i = 0; i < Number(raw); i++) names.push(name + (i ? `-${i}` : ""));
  }
  if (names.length > 512 || new Set(names).size !== names.length) fail();
  return names.sort();
}
function options(env) {
  // Queue connection factory uses URL directly, NOT REDIS_PASSWORD override.
  // Redis general-cache keyPrefix is distinct from BullMQ's prefix.
  for (const k of ["REDIS_CLUSTER_ENABLED", "REDIS_SENTINEL_ENABLED", "REDIS_TLS_ENABLED"])
    if (env[k] !== undefined && env[k] !== "false") fail();
  if (env.REDIS_KEY_PREFIX !== undefined || !env.REDIS_CONNECTION_STRING) fail();
  // Unknown shard variables cannot silently select namespaces we did not probe.
  for (const k of Object.keys(env))
    if (/^LANGFUSE_.*QUEUE_SHARD_COUNT$/.test(k) && !Object.values(SHARDS).includes(k)) fail();
  const u = new URL(env.REDIS_CONNECTION_STRING);
  if (u.protocol !== "redis:" ||
      !["langfuse-redis", "langfuse-redis.langfuse.svc", "langfuse-redis.langfuse.svc.cluster.local"].includes(u.hostname) ||
      (u.port && u.port !== "6379") || !["", "/", "/0"].includes(u.pathname) ||
      u.search || u.hash || (u.username && decodeURIComponent(u.username) !== "default") || !u.password) fail();
  return {host: u.hostname, port: 6379, db: 0, username: "default", password: decodeURIComponent(u.password),
    lazyConnect: true, enableOfflineQueue: false, enableReadyCheck: false,
    maxRetriesPerRequest: 0, retryStrategy: () => null, connectTimeout: 5000, commandTimeout: 5000};
}
async function checkNamespaces(client, names) {
  // Bounded SCAN of names only, never members/payloads. Unknown or stale queue
  // namespaces fail closed. No key is returned or hashed individually in output.
  const known = new Set(names); let cursor = "0", seen = 0, pages = 0;
  do {
    const reply = await client.scan(cursor, "MATCH", "bull:*", "COUNT", 256);
    if (!Array.isArray(reply) || reply.length !== 2 || typeof reply[0] !== "string" ||
        !/^[0-9]+$/.test(reply[0]) || !Array.isArray(reply[1])) fail();
    cursor = reply[0];
    if (++pages > 128 || (seen += reply[1].length) > 32768) fail();
    for (const key of reply[1]) {
      if (typeof key !== "string" || key.length > 4096 || !known.has(key.split(":")[1])) fail();
    }
  } while (cursor !== "0");
}
async function counts(client, names) {
  const totals = Object.fromEntries([...Object.keys(STATES), "paused_queues"].map(k => [k, 0]));
  for (const name of names) {
    const keys = [...Object.keys(STATES), "meta"].map(k => `bull:${name}:${k}`);
    const reply = await client.call("EVAL_RO", COUNT_LUA, keys.length, ...keys, ...Object.values(STATES));
    if (!Array.isArray(reply) || reply.length !== keys.length ||
        reply.some(n => !Number.isSafeInteger(n) || n < 0) || reply.at(-1) > 1) fail();
    Object.keys(totals).forEach((k, i) => { totals[k] += reply[i]; if (!Number.isSafeInteger(totals[k])) fail(); });
  }
  return totals;
}
async function main() {
  let client;
  const timer = setTimeout(() => { if (client) client.disconnect(); process.exit(1); }, 20000);
  try {
    const shared = sourceRoots();
    const names = registry(fs.readFileSync(path.join(shared, "server/queues.js"), "utf8"), process.env);
    const Redis = require(require.resolve("ioredis", {paths: ["/app/worker"]}));
    client = new Redis(options(process.env)); client.on("error", () => {});
    await client.connect();
    if (await client.ping() !== "PONG") fail();
    await checkNamespaces(client, names);
    const totals = await counts(client, names);
    await checkNamespaces(client, names);
    process.stdout.write(JSON.stringify({schema: 1, queue_count: names.length,
      registry_sha256: digest(JSON.stringify(names)), source_tree_sha256: TREES.map(t => t[1]),
      counts: totals, sampled_no_pending_work: Object.entries(totals).every(([k, n]) =>
        ["completed", "failed"].includes(k) || n === 0),
      writer_exclusion_verified: false, client_idleness_verified: false, capture_ready: false}) + "\n");
  } catch { process.exitCode = 1; }
  finally { if (client) client.disconnect(); clearTimeout(timer); }
}
module.exports = {TREES, SHARDS, STATES, COUNT_LUA, registry, options, counts, checkNamespaces, main};
if (require.main === module) main();
