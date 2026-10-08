# Research UI source provenance

The application integrates source adaptations of ThreeUI Community (MIT,
Copyright 2026 Meng To). It does not embed the ThreeUI documentation site or
claim that its branded application wrappers are unmodified upstream components.

## Verified reference revision

`5a736cd3c1f6f19802f61ebb10e1701b9f7aa26e`

| Upstream source | SHA-256 |
| --- | --- |
| AnimatedTopDock.tsx | 50ddbba7ebc81565f42bd14dda34efb45e7b18c1aa47e97f196256ffedb4478f |
| topDockController.ts | 506ab23d4d42cf1b5bc89131e7714586ee107381bb18d9b0302766e9a1dee2bd |
| creator-studio-intro.html | e14795f24ea8aa9cb0005ea740923289869de3250ac4ea18f58527cd42e18cbe |
| constellation-field.html | 1920ad4fe34f2ed2348e3a52110c37b4969bc45d71ff29f2738cb4542ad9f610 |
| fragment-mono.woff2 | 4f4dc27f4a770c0d02fde800daa836c8adc0d1e423b28da74baaf0d1cc3ab96c |

Source bundles: https://threeui.com/source-code/animated-top-dock.json,
https://threeui.com/source-code/threeui-intro.json,
https://threeui.com/source-code/constellation-field.json.
Original canonical reference files and MIT/OFL notices are under
`licenses/threeui/`.

## Application adaptations

- ResearchDock retains the exact author spring controller and modern command
  bar structure. Branding, navigation labels, active route, actions, spacing and
  colours are adapted to this application. Its numeric spring parameters remain
  122 / .19 / .70 / 17 / 16 / 3.5, x-axis, lockTrack=true.
- Intro derives from the verified canonical source and the author's first-beat
  isolation logic. It replaces branding with HyperChE, plays only 1.7 seconds,
  holds the last frame, and uses a static wordmark on a repeat visit.
- Constellation derives from the verified Canvas 2D implementation. It retains
  the node/link algorithm, excludes unrelated marketing dependencies, and adds
  parent pause/resume and cleanup. It is used only in the landing hero.
- The two HTML effects use isolated sandboxed srcDoc frames. They are local
  source assets and require no external CDN, images, analytics or model API.
- Fragment Mono is bundled under SIL OFL 1.1; Chinese text uses installed system
  fallback fonts. The report's small character subsets are not used as the only
  font for dynamic user text.

## Hypergraph rendering

RetrievalHyperGraph remains the project's Graphin/G6 implementation with the
original force-atlas2 and bubble-sets configuration. Adaptations add safe text
tooltips, stable edge identity, source details, display labels, node/edge
selection, zoom controls and ResizeObserver resizing. A local cache case is
labelled separately from the evidence returned for a live query.
