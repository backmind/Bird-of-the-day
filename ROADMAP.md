# Roadmap

Features under consideration. Contributions welcome.

## Image carousel (frontend)

The hero photo is a single image from Macaulay Library. A lightweight carousel with left/right arrows would let the reader browse additional photos of the same species. Macaulay Library's search API supports multiple results per species.

Considerations:
- Fetch N images per species instead of 1 (changes to `image_fetcher.py` and cache format)
- Minimal vanilla JS carousel (scroll-snap + arrow buttons), consistent with the current no-framework approach
- Each photo keeps its own photographer attribution
- RSS stays with the single hero image (carousels don't work in feeds)

## Photo collage for RSS

The RSS feed currently shows one hero photo. A Pillow-composed collage (hero image + smaller thumbnails) could give feed readers a richer visual without requiring interactive elements. Similar to how the distribution map is already composed server-side.

Considerations:
- Compose at feed-build time, cache as `maps/{code}.collage.png`
- Layout: large hero left, 2-3 smaller photos stacked right (or grid)
- All photographer attributions in the caption
- Balance file size vs visual richness

## Seasonal distribution maps

The current GBIF density map shows year-round occurrence. Many species have distinct breeding and wintering ranges. GBIF's map API may support a `month` parameter (undocumented but possibly functional) that could enable seasonal overlays with different colours.

Considerations:
- Test whether GBIF `month` parameter actually filters results
- If it works: compose 2-3 seasonal layers with distinct colour ramps + legend
- If not: would require downloading raw occurrence data and rendering custom maps (significantly more complex)
- Hemisphere-dependent seasons complicate a global map at zoom 0

## Field guide illustrations

AI-generated or sourced illustrations for identification tips. The most complex feature on the roadmap due to copyright constraints on existing field guide art.

Considerations:
- No free API for field guide illustrations exists
- AI generation (Stable Diffusion, DALL-E) could produce stylised illustrations but quality and accuracy vary
- Could start with silhouette/outline SVGs generated from species photos
