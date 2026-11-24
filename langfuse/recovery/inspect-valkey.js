"use strict";
// Read-only probe using the worker image's already-installed, configured client.
// No key names, payloads, credentials, arbitrary errors or INFO dumps are emitted.
function connectionOptions(env) {
  if (!env.REDIS_CONNECTION_STRING || env.REDIS_TLS_ENABLED === "true") {
    throw new Error("unsupported-configured-transport");
  }
  const url = new URL(env.REDIS_CONNECTION_STRING);
  if (url.protocol !== "redis:" ||
      !["langfuse-redis", "langfuse-redis.langfuse.svc", "langfuse-redis.langfuse.svc.cluster.local"].includes(url.hostname) ||
      (url.port && url.port !== "6379") ||
      !["", "/", "/0"].includes(url.pathname) || url.search || url.hash ||
      (url.username && decodeURIComponent(url.username) !== "default")) {
    throw new Error("configured-destination-not-admitted");
  }
  const password = env.REDIS_PASSWORD || decodeURIComponent(url.password);
  if (!password) throw new Error("configured-authentication-missing");
  return {host: url.hostname, port: 6379, db: 0, username: "default", password,
          lazyConnect: true, enableOfflineQueue: false, enableReadyCheck: false,
          maxRetriesPerRequest: 0, retryStrategy: () => null,
          connectTimeout: 5000, commandTimeout: 5000};
}

function persistenceSummary(text, config, count) {
  const info = Object.create(null);
  const wanted = new Set(["loading", "aof_enabled", "aof_rewrite_in_progress",
                          "aof_last_bgrewrite_status", "aof_last_write_status"]);
  for (const line of text.split(/\r?\n/)) {
    const split = line.indexOf(":");
    const key = line.slice(0, split);
    if (split > 0 && wanted.has(key)) {
      if (Object.hasOwn(info, key)) throw new Error("duplicate-persistence-field");
      info[key] = line.slice(split + 1);
    }
  }
  if (Object.keys(info).length !== wanted.size ||
      !["0", "1"].includes(info.loading) || info.aof_enabled !== "1" ||
      !["0", "1"].includes(info.aof_rewrite_in_progress) ||
      !["ok", "err"].includes(info.aof_last_bgrewrite_status) ||
      !["ok", "err"].includes(info.aof_last_write_status)) {
    throw new Error("persistence-state-not-admitted");
  }
  const expected = {appendonly: "yes", dir: "/data", appendfilename: "appendonly.aof",
                    appenddirname: "appendonlydir", dbfilename: "dump.rdb"};
  if (Object.keys(config).length !== Object.keys(expected).length ||
      Object.entries(expected).some(([key, value]) => config[key] !== value) ||
      !Number.isSafeInteger(count) || count < 0) {
    throw new Error("persistence-layout-not-admitted");
  }
  return {configured_native_authentication_verified: true,
          client: "worker-installed-ioredis", native_ping: "passed",
          aof_enabled: true, persistence_layout_verified: true,
          loading: info.loading === "1", rewrite_in_progress: info.aof_rewrite_in_progress === "1",
          last_rewrite_ok: info.aof_last_bgrewrite_status === "ok",
          last_write_ok: info.aof_last_write_status === "ok", database_keys: count,
          writer_exclusion_verified: false, queue_drain_verified: false};
}

async function main() {
  let client;
  const watchdog = setTimeout(() => {
    if (client) client.disconnect();
    process.exit(1);
  }, 15000);
  try {
    const options = connectionOptions(process.env);
    const library = require.resolve("ioredis", {paths: ["/app/worker"]});
    const Redis = require(library);
    client = new Redis(options);
    client.on("error", () => {});
    await client.connect();
    if (await client.ping() !== "PONG") throw new Error("native-ping-failed");
    const persistence = await client.info("persistence");
    const raw = await client.config("GET", "appendonly", "dir", "appendfilename", "appenddirname", "dbfilename");
    if (!Array.isArray(raw) || raw.length !== 10) throw new Error("config-response-not-admitted");
    const config = Object.create(null);
    for (let i = 0; i < raw.length; i += 2) {
      if (Object.hasOwn(config, raw[i])) throw new Error("duplicate-config-field");
      config[raw[i]] = raw[i + 1];
    }
    const result = persistenceSummary(persistence, config, await client.dbsize());
    process.stdout.write(JSON.stringify(result) + "\n");
  } catch {
    process.exitCode = 1;
  } finally {
    if (client) client.disconnect();
    clearTimeout(watchdog);
  }
}
module.exports = {connectionOptions, persistenceSummary, main};
if (require.main === module) main();
