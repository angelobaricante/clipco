# Clipco brand assets

The creator approved the solid three-facet C/play mark on October 10, 2026. `source/approved-logo.png` preserves that reference. All production variations share traced paths, including the original lettering, with smooth curves and sharp facet corners. The small gap at the play triangle's apex is intentional. Film perforations are absent.

## Choose an asset

| Use | Asset |
| --- | --- |
| App icon, favicon, compact placement | `assets/clipco-mark-black.svg` or `-white.svg` |
| Website navigation, wide banner | `assets/clipco-horizontal-black.svg` or `-white.svg` |
| Cover, vertical brand placement | `assets/clipco-stacked-black.svg` or `-white.svg` |
| Name where the mark is already present | `assets/clipco-wordmark-black.svg` or `-white.svg` |

Each SVG has a transparent PNG sibling. White files need a dark background to be visible. Artwork scales without font dependencies because the wordmark uses paths. Use black on light backgrounds and white on dark backgrounds. Keep the proportions and play triangle. Leave clear space of at least one quarter of the mark's width. For placements below 120 px, use the mark alone.

## Native Mac app

`app/Clipco/Assets.xcassets/AppIcon.appiconset` contains all ten required macOS size/scale entries, using seven unique PNG sizes. It contains the mark alone on a neutral rounded tile. Xcode compiles it into `AppIcon.icns` and wires the standard app/Dock/About icon through `CFBundleIconFile`.

`ClipcoMark.imageset` and `ClipcoLogo.imageset` preserve vector PDF representations and use template rendering. The existing setup sheet displays the horizontal logo with the system primary color, allowing the system to adapt it to light and dark appearance. No extra window controls or inference work were introduced.

## Website

`web/` contains an SVG favicon that adapts to light/dark browser appearance, 16/32/48 px PNG favicons, a 180 px touch icon, 192/512 px web icons, and `site.webmanifest`. SVG and PNG colors are black `#0E0D0C`, white `#FFFFFF`, and neutral background `#F7F6F2`.

Copy the required files into the website's public asset directory. Example head entries, assuming `/brand/` as the deployed asset path:

```html
<link rel="icon" type="image/svg+xml" href="/brand/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/brand/clipco-icon-32.png">
<link rel="apple-touch-icon" sizes="180x180" href="/brand/clipco-icon-180.png">
<link rel="manifest" href="/brand/site.webmanifest">
```

## Canva project

[Clipco - Brand, Website & Marketing](https://www.canva.com/folder/FAHXi5EUd7Y) contains a brand library, dedicated black/white logo variation designs, and website/social layouts. `canva-project.json` records final design IDs and edit links. The local SVG/PNG exports remain the reusable transparent masters.

Templates include a 1440×900 website hero, 1200×630 social link preview, 1080×1080 square post, 1080×1350 portrait post, 1080×1920 story, and 1280×720 video thumbnail. They use product-grounded draft copy and no private footage. No website or social post was published.

`canva/` includes PDF layouts and PNG previews. PDF pages use points; Canva imported the initial layouts at 96 dpi, so saved designs were corrected to the final pixel sizes. Dedicated logo variation PDFs already compensate for Canva's point-to-pixel conversion.

## Rebuild

On macOS with Swift and AppKit:

```sh
swift scripts/build-brand-assets.swift "$PWD" "$PWD/brand/source/approved-logo.png"
cd app
xcodegen generate
xcodebuild -project Clipco.xcodeproj -scheme Clipco -configuration Debug \
  -derivedDataPath /tmp/clipco-brand-build CODE_SIGNING_ALLOWED=NO build
```

Rebuilding updates local exports and the asset catalog. It does not upload or alter saved Canva designs.

## Provenance

The concept was generated with the built-in image generation tool and iterated at the creator's direction. Cursor's bold geometric style was the initial inspiration. Clipco's final mark and lettering are supplied assets, not copied Cursor artwork.
