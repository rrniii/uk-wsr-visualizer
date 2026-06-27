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

Use the data-selection controls to choose:

- radar,
- date range,
- pulse,
- variable,
- source object.

After selecting an item, the API hydrates the selected aggregate from the configured local path or public object-store URL.

## Radar controls

The viewer supports controls for:

- radar field and time selection,
- palette selection,
- opacity,
- range filters,
- azimuth filters,
- value filters,
- nearest-sweep height selection,
- click identify/readout.

## Caching model

Public object-store reads are cached locally under:

```text
~/Library/Application Support/UK WSR Visualizer/data/remote-aggregate-cache/
```

The cache is disposable. It can be cleared from the UI and is also bounded by time-to-live and size settings.

## Current scope

The browser UI focuses on functional controls that are already wired into the
local API. Bulk export products, object-store publication, and validation suites
remain primarily CLI/API workflows.
