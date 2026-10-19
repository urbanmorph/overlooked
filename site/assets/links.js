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

const INAT_UPLOAD = 'https://www.inaturalist.org/observations/upload';
const GBIF_PUBLISH = 'https://www.gbif.org/become-a-publisher';
const IUCN_PROCESS = 'https://www.iucnredlist.org/assessment/process';

// What a person can do next for one species, from its status, IUCN category and labels.
// sp: {status (0 listed only, 1 observed, 2 identified), iucn, codes (Set of label codes), wait (iNaturalist
// observations that wait for a name), identify (Identify page), gbifKey, name, paper (link to the description)}.
// Returns [{text, links: [{href, text}]}], the first step first.
export function nextSteps(sp) {
  const out = [], c = sp.codes, q = encodeURIComponent(sp.name);
  const gbifAll = gbifIndiaLinks(sp.gbifKey, true);
  if (sp.status === 0) {
    out.push({ text: c.has('nra') ? 'No observation is in the sources, and nobody has recorded it since it was described. Look for it where the description found it, and add what you find.'
      : 'No observation is in the sources. If you find it, add an observation, or publish the specimen records of your collection.',
    links: [...(c.has('nra') && sp.paper ? [{ href: sp.paper, text: 'The description' }] : []),
      { href: INAT_UPLOAD, text: 'Add an observation on iNaturalist' }, { href: GBIF_PUBLISH, text: 'Publish records on GBIF' }] });
  }
  if (sp.wait && sp.identify) {
    out.push({ text: `${sp.wait.toLocaleString('en-IN')} ${sp.wait === 1 ? 'observation on iNaturalist waits for a name. If you know the group, identify it.' : 'observations on iNaturalist wait for a name. If you know the group, identify them.'}`, links: [{ href: sp.identify, text: 'Identify on iNaturalist' }] });
  } else if (sp.status === 1) {
    out.push({ text: 'The records do not confirm the name yet. A specialist of the group can check the specimens or photos.', links: gbifAll.slice(0, 1) });
  }
  if (c.has('lnc') || c.has('lco') || c.has('lfl') || c.has('lm')) {
    out.push({ text: `Some records from India have no exact location, so they are not on the map.${c.has('lfl') ? ' Some coordinates may be wrong: such a record may not be from India.' : ''} The publisher of each record can correct it on GBIF.`,
      links: gbifAll.slice(1) });
  }
  if (c.has('nm')) out.push({ text: 'The name does not match the Catalogue of Life. A taxonomist can check the name.', links: [{ href: `https://www.catalogueoflife.org/data/search?q=${q}`, text: 'Search the Catalogue of Life' }] });
  const end = c.has('end') ? ' It is endemic to India, so records from India decide its assessment.' : '';
  if (!sp.iucn || sp.iucn === 'NE') out.push({ text: `The IUCN Red List has not assessed it.${end} Records with an exact place and date are the evidence for an assessment.`, links: [{ href: IUCN_PROCESS, text: 'How IUCN assesses a species' }] });
  else if (sp.iucn === 'DD') out.push({ text: `The IUCN Red List has too little data to give it a category.${end} More records from India help.`, links: [{ href: `https://www.iucnredlist.org/search?query=${q}`, text: 'IUCN Red List' }] });
  else if (['CR', 'EN', 'VU'].includes(sp.iucn)) out.push({ text: 'It is threatened on the IUCN Red List. Send new records from India to the state forest department, and check its protection under the Wild Life (Protection) Act, 1972.', links: [{ href: `https://www.iucnredlist.org/search?query=${q}`, text: 'IUCN Red List' }] });
  return out;
}
