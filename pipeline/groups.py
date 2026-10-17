"""Species groups, ported unchanged from fnf scripts/09_attention.py. Order matters: first match wins."""

import re

BUTTERFLY_FAMILIES = "('Papilionidae', 'Pieridae', 'Nymphalidae', 'Lycaenidae', 'Hesperiidae', 'Riodinidae')"
LARGE_MAMMAL_ORDERS = "('Carnivora', 'Proboscidea', 'Artiodactyla', 'Perissodactyla', 'Primates', 'Pholidota')"
LICHEN_CLASSES = "('Lecanoromycetes', 'Lichinomycetes', 'Arthoniomycetes')"

GROUP_SQL = f"""
    CASE
        WHEN class = 'Aves' THEN 'Birds'
        WHEN class = 'Mammalia' AND "order" IN {LARGE_MAMMAL_ORDERS} THEN 'Mammals: large (cats, elephants, deer, primates...)'
        WHEN class = 'Mammalia' AND "order" = 'Chiroptera' THEN 'Mammals: bats'
        WHEN class = 'Mammalia' AND "order" IN ('Rodentia', 'Eulipotyphla', 'Scandentia', 'Lagomorpha')
            THEN 'Mammals: rodents, shrews, hares'
        WHEN class = 'Mammalia' THEN 'Mammals: other (whales, dolphins...)'
        WHEN class IN ('Squamata', 'Testudines', 'Crocodylia', 'Reptilia') THEN 'Reptiles'
        WHEN class = 'Amphibia' THEN 'Amphibians'
        WHEN phylum = 'Chordata' AND (class IS NULL OR class IN ('Actinopterygii', 'Teleostei', 'Holostei',
                                                                  'Elasmobranchii', 'Holocephali')) THEN 'Fish'
        WHEN "order" = 'Lepidoptera' AND family IN {BUTTERFLY_FAMILIES} THEN 'Insects: butterflies'
        WHEN "order" = 'Lepidoptera' THEN 'Insects: moths'
        WHEN "order" = 'Odonata' THEN 'Insects: dragonflies & damselflies'
        WHEN "order" = 'Coleoptera' THEN 'Insects: beetles'
        WHEN "order" = 'Hymenoptera' THEN 'Insects: bees, wasps, ants'
        WHEN "order" = 'Diptera' THEN 'Insects: flies'
        WHEN "order" = 'Hemiptera' THEN 'Insects: true bugs'
        WHEN class = 'Insecta' THEN 'Insects: other'
        WHEN class = 'Arachnida' THEN 'Spiders & other arachnids'
        WHEN phylum = 'Mollusca' THEN 'Molluscs'
        WHEN class = 'Malacostraca' THEN 'Crabs, shrimps & kin'
        WHEN phylum = 'Tracheophyta' AND family = 'Orchidaceae' THEN 'Plants: orchids'
        WHEN phylum = 'Tracheophyta' AND family IN ('Poaceae', 'Cyperaceae') THEN 'Plants: grasses & sedges'
        WHEN phylum = 'Tracheophyta' AND class IN ('Polypodiopsida', 'Lycopodiopsida') THEN 'Plants: ferns & lycophytes'
        WHEN phylum = 'Tracheophyta' THEN 'Plants: other flowering plants & conifers'
        WHEN phylum IN ('Bryophyta', 'Marchantiophyta', 'Anthocerotophyta') THEN 'Mosses & liverworts'
        WHEN kingdom = 'Fungi' AND class IN {LICHEN_CLASSES} THEN 'Lichens'
        WHEN kingdom = 'Fungi' THEN 'Fungi'
        WHEN phylum IN ('Rhodophyta', 'Chlorophyta', 'Charophyta', 'Ochrophyta') THEN 'Algae & diatoms'
        ELSE 'Other'
    END
"""

# The groups in GROUP_SQL order, 'Other' last. Site files of the master list index into this list.
GROUPS = list(dict.fromkeys(re.findall(r"THEN '([^']+)'", GROUP_SQL))) + ["Other"]
