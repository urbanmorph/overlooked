// Every site script parses as a module. A page script that fails to parse leaves its page on "Loading..." with no
// error shown, and most page scripts are not imported by any other test. Run: node --test tests/syntax.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const dir = new URL('../site/assets/', import.meta.url);
for (const f of readdirSync(dir).filter(f => f.endsWith('.js'))) {
  test(`${f} parses`, () => {
    const r = spawnSync(process.execPath, ['--input-type=module', '--check'], { input: readFileSync(new URL(f, dir)) });
    assert.equal(r.status, 0, r.stderr.toString());
  });
}
