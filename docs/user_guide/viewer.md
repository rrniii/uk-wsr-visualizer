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

- choose the **Data era** first: **Dual-polarisation era** uses the published
  PVOL catalog, while **Pre-dual-polarisation era** uses a separately configured
  single-polarisation REF/DOP PVOL catalog;
- enter a start and end date as `YYYY-MM-DD`;
- choose one of the radars available for that date range;
- choose a pulse if needed, or leave it as **Any**;
- select a catalog item.

The availability panel reports the loaded catalog range and disables radars that
do not overlap the selected dates. After selecting an item, the local API
hydrates the selected source object from the configured local path or public
object-store URL and enables only the valid variable, time, and elevation
choices found in that source object.

The eras are intentionally not merged. This prevents a pre-dual source from
being interpreted as though dual-polarisation variables should be available.
The desktop default is the published dual-polarisation catalog. Deployments can
set `UK_WSR_VISUALIZER_PRE_DUAL_POL_REMOTE_CATALOG_URL` when the pre-dual PVOL
catalog has been published. Until then, the source selector reports that the
archive cannot be reached rather than falling back to a different data era.

## Radar controls

The viewer supports controls for:

- radar field and time selection,
- opacity,
- elevation selection,
- mouse wheel or trackpad zoom, drag pan, double-click zoom, touch pan/pinch
  where supported, and click identify/readout.

The pointer readout can show value, range, azimuth, beam height, elevation, bin,
and latitude/longitude. Toggle these fields from the **Pointer** controls above
the map.

## Noise and clutter removal

The viewer enables **Remove confirmed noise and clutter** in `qc-v3` safe mode
by default. Processing happens in memory and never writes to, alters, or
republishes the source PVOL HDF5 file. Safe mode removes only high-confidence
receiver noise supported by converging evidence. Weather, birds, insects,
mixed echoes, and uncertain gates remain visible.

Learned background evidence runs in shadow: the app can report proposals and
abstentions, but it cannot apply learned deletion without a validated,
stratum-matched release bundle. Standalone texture-speckle, broad
companion-field filtering, and unaudited long-range-noise fields are disabled
because they can remove real weak signal.

Specialist display and filtering controls are kept in **Advanced diagnostics and
filters**. Use that section when you need to change palette, display limits,
range rings, range/azimuth/value filters, CAPPI-style height filters, or cleanup
diagnostics. These options are useful for audit and method development, but
most users should retain the safe defaults.

## Recent selections

Successful primary-panel plots are stored as recent selections on the local
device. Use **Recent Selections** to reopen a radar/date/pulse/time/variable/
elevation combination without searching the catalog again. Recent selections are
stored in the app data directory, not in the source radar files.

## Four-panel comparison

Use **4 Panel** to compare related source objects. Each panel has its own item,
variable, and elevation selector. Time and map view are linked by default, while
variable and elevation remain independent unless you explicitly enable those
**Link** controls. When elevation linking is enabled, the app matches panels by
elevation angle rather than by sweep/dataset number, so different radars can
still be compared at the closest available elevation.

If the linked time is not available for a panel, that panel shows a message
instead of trying to plot an invalid selection.

## Export and provenance

Use **Export & Provenance** to create a current-view screenshot, polar PPI PNG,
polar PPI MP4 animation, georeferenced KMZ/GeoTIFF product, or metadata JSON
export from the current primary panel. Server-backed exports write an artifact
manifest. The screenshot export downloads a local manifest beside the PNG. The
manifest records the software version, selected radar/date/time/variable,
elevation, coordinate mode, source object, citation metadata, and generated
artifact checksums where available.

During animation, the viewer keeps the current frame visible while the next
frame loads. Use **Fit View** only when you want to reset the map extent; normal
time stepping and playback preserve the current zoom/pan view.

## Caching model

Public object-store reads are cached locally under:

```text
~/Library/Application Support/UK WSR Visualizer/data/remote-aggregate-cache/
```

The cache is disposable. It can be cleared from the UI and is bounded by size using least-recently-used eviction. Catalogue JSON and field-index sidecars are cached separately so returning to the same radar/day is fast even before a raw HDF5 file is downloaded.

## Current scope

The viewer focuses on functional controls that are wired into the local API.
Advanced bulk exports, derived math products, tile generation, and validation
suites remain CLI/API workflows.
