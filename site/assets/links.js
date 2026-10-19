// Links to the sites where people can act on a species: GBIF records from India, found by GBIF's own species key.

const GBIF_SEARCH = 'https://www.gbif.org/occurrence/search';

// The GBIF key from a reply of api.gbif.org/v1/species/match, only for an exact match (the accepted name for a synonym).
export function gbifKeyOf(match) {
  if (!match || match.matchType !== 'EXACT') return null;
  return (match.synonym ? match.acceptedUsageKey : match.usageKey) ?? null;
}

// GBIF records of the species from India; with noExactLocation, also the ones with no coordinates, to correct.
export function gbifIndiaLinks(key, noExactLocation) {
  if (key == null) return [];
  const all = `${GBIF_SEARCH}?country=IN&taxon_key=${encodeURIComponent(key)}`;
  return [{ href: all, text: 'GBIF: records from India' },
    ...(noExactLocation ? [{ href: `${all}&has_coordinate=false`, text: 'GBIF: records from India with no coordinates (correct them at the source)' }] : [])];
}
