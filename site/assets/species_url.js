// The address of a species page: /species/<key>/<slug of its Latin name>. The key finds the species; the slug puts
// its name in the address for people and search engines, and a wrong one is corrected (functions/species/[[path]].js).
// pipeline/master.py slug() makes the same slug for the sitemaps (tests/fixtures/species_slugs.json holds both to it).

/** The Latin name in lower case, accents dropped, every run of other characters one hyphen. */
export const slug = name => String(name ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

/** The path of a species page; with no name, just the key (the page then corrects the address). */
export const speciesPath = (key, name) => {
  const s = slug(name);
  return `/species/${encodeURIComponent(key)}${s ? `/${s}` : ''}`;
};
