// Places and groups for the place pages (/in/<place>/<group>, functions/in/[[path]].js): their names, slugs and
// addresses. A place is India, a state (a species is there with an open record placed there), a WII biogeographic
// zone or a district (a GBIF record placed there). The groups and states come from the week's summary.json, so a new one gets
// pages without a change here; only the words for a title (GROUP_NOUNS, ZONE_TITLES) are written out.
import { slug } from '../../site/assets/species_model.js';

/** A page is worth indexing, and goes in the sitemap, from this many species. Fewer: the page is noindex. */
export const MIN_SPECIES = 10;

/** How a title says the group: "Birds of Kerala", "Bees, wasps and ants of Assam". */
const GROUP_NOUNS = {
  'Birds': 'birds', 'Mammals: large (cats, elephants, deer, primates...)': 'large mammals', 'Mammals: bats': 'bats',
  'Mammals: rodents, shrews, hares': 'rodents, shrews and hares', 'Mammals: other (whales, dolphins...)': 'whales, dolphins and other mammals',
  'Reptiles': 'reptiles', 'Amphibians': 'amphibians', 'Fish': 'fish', 'Insects: butterflies': 'butterflies',
  'Insects: moths': 'moths', 'Insects: dragonflies & damselflies': 'dragonflies and damselflies', 'Insects: beetles': 'beetles',
  'Insects: bees, wasps, ants': 'bees, wasps and ants', 'Insects: flies': 'flies', 'Insects: true bugs': 'true bugs',
  'Insects: other': 'other insects', 'Spiders & other arachnids': 'spiders and other arachnids', 'Molluscs': 'molluscs',
  'Crabs, shrimps & kin': 'crabs, shrimps and kin', 'Plants: orchids': 'orchids', 'Plants: grasses & sedges': 'grasses and sedges',
  'Plants: ferns & lycophytes': 'ferns and lycophytes', 'Plants: other flowering plants & conifers': 'other flowering plants and conifers',
  'Mosses & liverworts': 'mosses and liverworts', 'Lichens': 'lichens', 'Fungi': 'fungi', 'Algae & diatoms': 'algae and diatoms',
  'Other': 'other species',
};

/** How a title says the zone: "Amphibians of the Western Ghats". */
const ZONE_TITLES = {
  'Trans-Himalaya': 'the Trans-Himalaya', 'Himalaya': 'the Himalaya', 'Desert': 'the Thar and Kutch deserts',
  'Semi-Arid': 'the semi-arid zone', 'Western Ghats': 'the Western Ghats', 'Deccan Peninsula': 'the Deccan Peninsula',
  'Gangetic Plain': 'the Gangetic Plain', 'Coasts': 'the coasts of India', 'North-East': 'North-East India',
  'Islands': 'the Andaman, Nicobar and Lakshadweep islands',
};

const cap = s => s.charAt(0).toUpperCase() + s.slice(1);

/** The group as a plural noun in lower case ("bees, wasps and ants"); a group not written out reads as its name. */
export const groupNoun = name => GROUP_NOUNS[name] ?? name.toLowerCase();
/** "Bees, wasps and ants". */
export const groupTitle = name => cap(groupNoun(name));
/** The group's part of an address: its name without the bracket ("mammals-large", "insects-bees-wasps-ants"). */
export const groupSlug = name => slug(name.replace(/\s*\(.*?\)/g, ''));

/** What every page and answer for a district says: what "in the district" means, how to read it, and respect for the
 *  species (the place pages and the agent server, lib/mcp.js). */
export const DISTRICT_NOTE = 'A species is in a district when a GBIF record of it is placed in the district. This does not show that it lives there now: '
  + 'look at the year of the latest record there. A record can be in the wrong district: some sources move records of species at risk to a random point nearby, '
  + 'and some records give only an approximate place. When a species is not on the list, there is no record of it there, not that it is absent. '
  + 'Districts with few naturalists have fewer records.';
export const RESPECT_NOTE = 'Many of these species are protected under the Wild Life (Protection) Act, 1972. Do not use this list to find, disturb, collect or trade them.';

/** Every place, India first, then the states A to Z, then the zones in WII's order, then the districts (d/places.json,
 *  by state and name): {slug, kind: india|state|zone|district, name, title (as a title says it), filter (for
 *  speciesWhere), code (a state's or district's LGD code); a district also state (its state as a place) and counts}.
 *  A district's slug has its state's, as two states can have a district of the same name. */
export function places(S, districts = []) {
  const states = [...S.states].sort((a, b) => a.name.localeCompare(b.name)).map(s => {
    const name = s.name.replace(/ & /g, ' and ');
    return { slug: slug(s.name), kind: 'state', name, title: name, filter: { state: s.code }, code: s.code };
  });
  const zones = [...new Set(S.provinces.map(p => p[2]))].map(z =>
    ({ slug: slug(z), kind: 'zone', name: z, title: ZONE_TITLES[z] ?? `the ${z}`, filter: { region: z } }));
  const stateOf = new Map(states.map(s => [s.code, s]));
  const dists = districts.filter(d => stateOf.has(d.state)).map(d => {
    const st = stateOf.get(d.state);
    return { slug: `${slug(d.name)}-${st.slug}`, kind: 'district', name: d.name, title: `${d.name}, ${st.name}`,
      filter: { district: d.code }, code: d.code, state: st, counts: d.groups };
  }).sort((a, b) => a.state.name.localeCompare(b.state.name) || a.name.localeCompare(b.name));
  return [{ slug: 'india', kind: 'india', name: 'India', title: 'India', filter: {} }, ...states, ...zones, ...dists];
}

/** /in, /in/<place> or /in/<place>/<group>. */
export const placePath = (place, group) => `/in${place ? `/${place.slug ?? place}` : ''}${group != null ? `/${groupSlug(group)}` : ''}`;

/** The counts of a place from placeCounts (lib/mcp.js): species per group. */
export const countsOf = (C, place) => (place.kind === 'india' ? C.india : place.kind === 'state' ? C.states[place.code]
  : place.kind === 'district' ? place.counts : C.zones[place.name]) || [];
