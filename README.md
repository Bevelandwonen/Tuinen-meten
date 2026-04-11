#### INTRO TEXT








# STEPS:

# Get data:
Ga naar: https://app.pdok.nl/lv/bgt/download-viewer/
- Selecteer het gebied
- Download het bestand
- Extract hem in data/bgt (We only need: bgt_wegdeel.gml and bgt_pand.gml)

Ga naar: https://service.pdok.nl/lv/bag/atom/bag.xml
- Download BAG geopackage
- Extract deze in data/bag

Ga naar: https://app.pdok.nl/kadaster/kadastralekaart/download-viewer/
- Selecteer het gebied
- Download het bestand
- Extract hem in data/kad

Zet lijst met bag_ids in data/bag_ids:
- Naam bag_ids.xlsx of csv
- Zorg dat de kolom: Pand Id aanwezig is.


# Script runnen

- Run plot_house_matcher.py
Dit matched per eenheid het juiste plot

- Run inspect results.py
Draw all results?


- calc garden size manual
-> zet zelf de grenzen



add information about the different data types and files we load