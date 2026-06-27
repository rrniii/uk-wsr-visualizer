# Viewer

The viewer is an interactive map-based interface for exploring UK WSR aggregate
HDF5 radar fields.

## Start the viewer

```bash
uk-wsr-visualizer api --catalog data/catalog.json --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

The macOS app bundle starts the same local service and opens the viewer automatically.

## Data selection

Use the data-selection controls date-first:

- enter a start and end date as `YYYY-MM-DD`;
- choose one of the radars available for that date range;
- choose a pulse if needed, or leave it as **Any**;
- select a catalog item.

The availability panel reports the loaded catalog range and disables radars that
do not overlap the selected dates. After selecting an item, the local API
hydrates the selected source object from the configured local path or public
object-store URL and enables only the valid variable, time, and elevation
choices found in that source object.

## Radar controls

The viewer supports controls for:

- radar field and time selection,
- palette selection,
- opacity,
- display min/max scaling,
- optional range-dependent noise-floor masking,
- range rings and ring spacing,
- range filters,
- azimuth filters,
- value filters,
- elevation selection,
- mouse wheel zoom, drag pan, double-click zoom, and click identify/readout.

The pointer readout can show value, range, azimuth, beam height, elevation, bin,
and latitude/longitude. Toggle these fields from the **Pointer** controls above
the map.

The status strip above the map summarises the plotted radar, date, pulse, time,
variable, elevation, palette, opacity, noise-floor state, and source object. Use
this strip as the quick check before saving screenshots or creating exports.

## Noise-floor masking

UK single-site radar fields can contain a range-dependent background floor. The
viewer leaves data unchanged by default. To inspect a cleaner quick-look field,
enable **Remove range-dependent noise floor** in **Radar Controls**.

The current method estimates a profile across range bins and masks gates whose
values are within the selected margin above that profile. The default margin is
3 dB. The plot message and status strip report when masking is enabled and how
many gates were masked.

Use this as an exploratory display control, not as a permanent correction to
the source object. Exports and manifests record the selected processing state so
figures can be interpreted later.

## Four-panel comparison

Use **4 Panel** to compare related source objects. Each panel has its own item,
variable, and elevation selector. Time remains linked globally across all
panels. The **Link** controls can also link map view, variable, and elevation
when that is useful for a comparison.

If the linked time is not available for a panel, that panel shows a message
instead of trying to plot an invalid selection.

## Export and provenance

Use **Export & Provenance** to create a PNG quick-look or metadata JSON export
from the current primary panel. Each export writes an artifact manifest. The
manifest records the software version, selected radar/date/time/variable,
source object, citation metadata, and generated artifact checksums.

## Caching model

Public object-store reads are cached locally under:

```text
~/Library/Application Support/UK WSR Visualizer/data/remote-aggregate-cache/
```

The cache is disposable. It can be cleared from the UI and is also bounded by time-to-live and size settings.

## Current scope

The viewer focuses on functional controls that are wired into the local API.
Advanced bulk exports, derived math products, tile generation, and validation
suites remain CLI/API workflows.
