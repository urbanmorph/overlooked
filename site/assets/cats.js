// Group families for the home page and the Records to fix page, built from the 28 pipeline groups by name:
// [key, name, test on a group name].
export const CATS = [
  ['insects', 'Insects', g => g.startsWith('Insects:')],
  ['plants', 'Flowering plants and ferns', g => g.startsWith('Plants:')],
  ['fungi', 'Fungi and lichens', g => g === 'Fungi' || g === 'Lichens'],
  ['mosses', 'Mosses, liverworts and algae', g => g === 'Mosses & liverworts' || g === 'Algae & diatoms'],
  ['fish', 'Fish', g => g === 'Fish'],
  ['inverts', 'Molluscs, spiders and crabs', g => ['Molluscs', 'Spiders & other arachnids', 'Crabs, shrimps & kin'].includes(g)],
  ['herps', 'Amphibians and reptiles', g => g === 'Amphibians' || g === 'Reptiles'],
  ['birds', 'Birds', g => g === 'Birds'],
  ['mammals', 'Mammals', g => g.startsWith('Mammals')],
  ['other', 'Other', g => g === 'Other'],
];
