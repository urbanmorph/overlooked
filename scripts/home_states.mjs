// Writes site-parts/states.html, the homepage's plain links to every state page, from the week's published summary
// (its states, as the place pages name them). Run when a state is added or renamed, then scripts/pages.py.
// Usage: node scripts/home_states.mjs
import { writeFileSync } from 'node:fs';
import { stateLinks } from '../functions/lib/places.js';

const SITE = 'https://yellide.com';
const { base } = await (await fetch(`${SITE}/data/layers/master/latest.json`)).json();
const S = await (await fetch(`${SITE}/data/${base}summary.json`)).json();
writeFileSync(new URL('../site-parts/states.html', import.meta.url), `<section class="card pad" aria-labelledby="states-h">
    <h2 id="states-h" style="font-size:20px">Species by state</h2>
    <p class="muted">Each page lists the species with an open record in the state, by group.</p>
    <ul class="state-links">
${stateLinks(S)}
    </ul>
  </section>
`);
console.log(`site-parts/states.html: ${S.states.length} states`);
