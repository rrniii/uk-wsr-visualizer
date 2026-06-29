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

The radar availability chips below the catalog summary give a compact date-range
check. Available radars are shown normally; radars without loaded data for the
selected range are greyed out. This is especially useful while interim
object-store publishes are still incomplete.

For PVOL object-store catalogs, radar site coordinates are read from the root
catalog. This lets the viewer offer **Nearest radar** and radar-site map
overlays without loading any per-day file catalogs at startup. Missing or
invalid site coordinates are treated as unavailable rather than plotted at a
placeholder location.

## Radar controls

The viewer supports controls for:

- radar field and time selection,
- optional calibration/diagnostic variable inspection,
- palette selection,
- opacity,
- display min/max scaling,
- optional range-dependent noise-floor masking,
- optional pre-VP noise and clutter masking for BioDAR / UKMO NIMROD PVOL profile workflows,
- range rings and ring spacing,
- radar-site overlays,
- range filters,
- azimuth filters,
- value filters,
- elevation selection,
- mouse wheel zoom, drag pan, double-click zoom, and click identify/readout.

The pointer readout can show value, range, azimuth, beam height, elevation, bin,
and latitude/longitude. Toggle these fields from the **Pointer** controls above
the map. Use **Copy Readout** to copy the current pointer/click readout, or
**Pin Readout** to keep important gate readouts visible while stepping through
time, variable, or elevation.

Calibration and diagnostic fields such as noise records, SQI/NCP, CI, and
calibration-like variables are hidden from the main **Variable** list by
default. Enable **Show calibration/diagnostic variables** only when you are
deliberately inspecting those inputs. They should normally be treated as
metadata or quality inputs rather than publication plot variables.

The status strip above the map summarises the plotted radar, date, pulse, time,
variable, elevation, palette, opacity, noise-floor state, and source object. Use
this strip as the quick check before saving screenshots or creating exports.

If a loaded field looks blank, first clear the range, azimuth, and value
filters. A narrow azimuth sector can legitimately contain no visible gates. For
`RHOHV` and other correlation-coefficient fields, the default display range is
`0.0-1.05` so lower-quality or noisy areas remain visible for inspection.

## Reference maps

The **Basemap** selector provides keyless public map contexts:

- **OpenStreetMap streets**: the default reference map for general use;
- **OpenStreetMap no labels**: a quieter map when radar echoes need visual
  priority;
- **OpenStreetMap dark**: a dark reference map for screen work;
- **Range grid**: no web map, only radar range and azimuth context;
- **Dark analysis**: a dark local background for dense fields;
- **Light presentation**: a light local background for screenshots and papers.

The optional **Place/road labels** and **Terrain/hillshade** overlays add public
OpenStreetMap/terrestris WMS layers on top of the selected map. Labels are drawn
above the radar layer so they remain readable; terrain is drawn below the radar
layer so the data stay visible. These overlays use normal browser fetches and
are not bulk downloaded or cached by the app.

OpenStreetMap attribution remains visible in the viewer and in captured
screenshots when a public reference map or overlay is enabled. Google Maps and
OS Open Zoomstack are not used in the current desktop app because they require
separate service terms, keys, or data packaging decisions.

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

## Pre-VP filtering

The **Pre-VP Filtering** panel controls masks that are applied in memory
immediately before BioDAR / UKMO NIMROD PVOL vertical-profile calculations. The
source aggregate or pvol HDF5 files are never overwritten.

The operational default is **Recommended: current + CI <= 4**. Validation across
426 pvol files and 24 mask profiles found this setting to be a good operational
compromise. It is deliberately conservative: it removes more clutter-like signal
than the current combined mask while retaining enough high-bird proxy signal for
production VP/VPTS generation.

Available presets are:

- **Off / baseline**: no pre-VP mask, useful for comparison runs;
- **Current combined**: SQI/NCP, estimated noise-floor, and static-clutter
  components with no CI threshold;
- **Recommended: current + CI <= 4**: the production default;
- **Aggressive sensitivity: CI <= 4**: a stronger lower-bound option for
  publication sensitivity checks;
- **Custom**: advanced settings for controlled sensitivity tests.

When a gate is masked for VP/VPTS processing, the mask is applied to every
same-shaped field used by the calculation by setting that gate to `NaN` in the
in-memory arrays. This keeps the operation reproducible without creating a
modified HDF5 source file. Saved project/session state records the selected
preset and custom parameters.

Use **Preview Pre-VP Masks** to compare raw decoded DBZH with the current
combined, recommended, and aggressive masks for the selected radar, time, and
elevation. The preview renders masked gates as white and reports total gates,
masked fraction, component-level masked fractions, and warnings such as missing
NCP or CI fields. Custom CI `>= 6` or `>= 7` settings are deliberately marked as
advanced because validation found those rules too destructive for default
production use.

## Four-panel comparison

Use **4 Panel** to compare related source objects. Each panel has its own item,
variable, and elevation selector. Time remains linked globally across all
panels. The **Link** controls can also link map view, variable, and elevation
when that is useful for a comparison.

If the linked time is not available for a panel, that panel shows a message
instead of trying to plot an invalid selection.

Use **4 Elevations** to fill four panels with the same item, variable, and time
at up to four elevations. Use **4 Variables** to fill four panels with normal
radar moments at the same item, time, and matched elevation where possible.
**Fit Sweep** resets each visible panel back to the loaded sweep extent.

## Diagnostics

Use **Diagnostics** in the header when the app behaves unexpectedly. The dialog
reports the running software version, catalog mode and source, catalog summary,
raw-cache location, and raw-cache size. It is intended for beta testing and
support messages; it does not load every day catalog at startup.

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
