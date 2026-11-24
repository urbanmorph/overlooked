// Helpers the server-drawn pages share: lib/species_page.js and lib/place_page.js.

/** Names joined the way a sentence does: "A", "A and B", "A, B and C". */
export const andList = xs => (xs.length < 3 ? xs.join(' and ') : `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}`);

/** The page with one meta tag's content set to `value` (already escaped). A function as the replacement, so a $ in the
 * value stays as it is. */
export function replaceMeta(html, attr, name, value) {
  return html.replace(new RegExp(`<meta ${attr}="${name}" content="[^"]*">`), () => `<meta ${attr}="${name}" content="${value}">`);
}
