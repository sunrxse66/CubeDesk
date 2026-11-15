# Modular coastal village

The active world is assembled from independent 16-pixel terrain tiles and independent transparent object sprites. There is no full-map painting or generated seasonal atlas in the renderer.

## Sources

Pixel Frog, **Tiny Swords Update 010**, downloaded from the official author's page:
https://pixelfrog-assets.itch.io/tiny-swords

The download used is explicitly labelled **TS_old version_CC0 Licensed** (3 January 2024). Only that old CC0 edition is imported; the current Free Pack has different terms and is not used. `tiles/provenance.json` records the source paths and exact archive SHA-256. `tiles/CC0-1.0.txt` contains the dedication.

Reimport with `python prepare_village_tiles.py archive.zip`. The importer rejects a different archive. Runtime has no download dependency.

## Structure

- `world.json`: an editable 40-by-32 tile grid, named locations, garden bounds, and independent object placements. Every building, tree, rock and market stall has its own identity and asset reference. Solid objects define ground footprints separately from their visual canopy/roof.
- `tiles/ground.png`: the author's modular grass and sand tiles, recolored at runtime for seasons and earthy paths.
- `tiles/bridge.png`: modular bridge and pier deck pieces.
- `tiles/house-*.png`, `tower.png`, `inn.png`, `workshop.png`: independent building sprites.
- `tiles/tree.png`, `worker.png`: original animation sheets. Trees sway and workers walk/idle using actual authored animation frames. Outfit recoloring and animal ears preserve CubeDesk character customization.
- `tiles/deco-*.png`: independent vegetation, mushrooms and rocks.
- Small stalls, fountain, lamps, flowerbeds, planters, benches, mailboxes, fences, crates, barrels, wood piles, well, boats, fishing gear, mill sails, lighthouse lantern, growing crops, butterflies, chimney smoke, weather and story effects are original code-drawn CubeDesk props, not crops of an illustration.

`village_tiles.py` assembles and caches only the ground. `village_art.py` depth-sorts independent sprites and moving residents, allowing them to pass behind roofs and tree crowns. `village_map.py` derives water, bridge passages and solid ground footprints from the same map and supplies cached A* routes without diagonal corner cutting. The overview is rendered from the same live scene as the following camera.

The game computes on the PC. This change does not flash or change the cube firmware. Default streaming stays at 80-by-80 with full-screen scaling for the ESP8266.

The brighter palette preserves seasonal shading. Orchard crowns reuse the author's shrub texture with original trunks and fruit. Courtyard details have explicit object placements; solid yard props share the navigation model. Flowerbeds and shoreline boats do not block navigation. Ambient effects are local and small; static props use cached sprites.
