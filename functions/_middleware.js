// Counts usage after the response is ready (see lib/metrics.js and docs/metrics.md).
// The response is returned unchanged. Without the DB binding, nothing is counted.
import { observe, record } from './lib/metrics.js';

export async function onRequest({ request, env, next, waitUntil }) {
  const response = await next();
  if (env.DB) {
    try {
      const pairs = observe(request, response);
      if (pairs.length) waitUntil(record(env.DB, new Date().toISOString().slice(0, 10), pairs));
    } catch {
      // metrics must never change a response
    }
  }
  return response;
}
