// No API keys: use is counted by mode (website, API, MCP, downloads; bots excluded) as daily totals. The
// User-Agent is read only to sort a request into a mode and is not stored. The docs ask for it in those words.
// Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const read = (f) => fs.readFileSync(new URL('../' + f, import.meta.url), 'utf8');
const ASK = "Please send a `User-Agent` that names your app (for example `my-app/1.0`). We read it only to tell apps, "
  + "AI tools and crawlers apart, so our counts of how each mode is used stay honest. We don't store it, and we don't "
  + 'track who you are.';
const MCP = 'AI apps send their own name when they connect. We count calls by app (Claude, Cursor, …) and keep nothing else.';
const flat = (s) => s.replace(/\s+/g, ' ');

test('llms.txt and the README ask for a User-Agent and say what the MCP server counts', () => {
  for (const f of ['site/llms.txt', 'README.md']) {
    assert.ok(flat(read(f)).includes(ASK), f);
    assert.ok(flat(read(f)).includes(MCP), f);
  }
});
