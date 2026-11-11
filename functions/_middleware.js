// Sends the old address and www to yellide.com, where the site lives since 11 Nov 2026: the same page, for good.
// Then counts usage after the response is ready (see lib/metrics.js and docs/metrics.md).
// The response is returned unchanged. Without the DB binding, nothing is counted.
import { observe, record } from './lib/metrics.js';

const HOME = 'yellide.com';
const MOVED = new Set(['overlooked-india.pages.dev', 'www.yellide.com']);   // previews (<id>.overlooked-india.pages.dev) stay
// Search Console's file check fails on a redirect to another domain: the old property keeps its file, so it stays
// verified for Change of Address. Pages serves it at its name without .html.
const VERIFICATION = /^\/google[0-9a-f]+(\.html)?$/;

export async function onRequest({ request, env, next, waitUntil }) {
  const url = new URL(request.url);
  if (MOVED.has(url.hostname) && !VERIFICATION.test(url.pathname)) return Response.redirect(`https://${HOME}${url.pathname}${url.search}`, 301);
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
