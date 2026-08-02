# Troubleshooting

Start with the message at the top of the application. It distinguishes catalogue
loading, source download, rendering, and export failures. Keep the current
radar, date, pulse, time, variable, elevation, and app version when reporting a
problem.

## The app does not start

Check the platform log:

| Platform | Log location |
|---|---|
| macOS | `~/Library/Application Support/UK WSR Visualizer/uk-wsr-visualizer.log` |
| Windows | `%LOCALAPPDATA%\\UK WSR Visualizer\\uk-wsr-visualizer.log` |
| Linux | `~/.local/state/uk-wsr-visualizer/uk-wsr-visualizer.log` |

The desktop wrapper starts a private server on the local computer. If its
preferred port is occupied, current packages try another local port. The
Windows package also requires the Microsoft Edge Evergreen WebView2 Runtime.

## The catalogue loads but no day is available

1. Check that the selected date lies inside the catalogue snapshot.
2. Choose the date before the radar; unavailable radars are disabled.
3. Leave pulse as **Any** until a day has been selected.
4. Press **Retry loading data** or **Refresh** after a temporary network error.

An absent date means absent from the loaded catalogue. It does not, by itself,
prove that no historical data exist in CEDA.

## A variable, time, or elevation is missing

The controls are constrained by the selected HDF5 volume. Change pulse or time
and inspect the list again. Long-pulse and short-pulse scans can contain
different ranges, fields, and elevation sets.

Optional field-index sidecars can make selection faster. If a sidecar is
absent, the app scans the selected HDF5 file and then populates the same
controls; the first load will therefore take longer.

## The first plot is slow

The first plot may require a source download plus HDF5 decoding. The source
cache is a size-bounded, least-recently-used cache with a default maximum of
25 GB. Repeated plots of the same volume should be faster. Adjacent animation
frames are prefetched when possible.

Use **Performance** to distinguish catalogue, download, HDF5, processing, and
render time. Use **Clear Raw Cache** only when you need to remove local source
objects or diagnose a fresh download.

## The plot looks blank

- Confirm that the display minimum and maximum suit the selected variable.
- Use the full-auto display reset after changing variables.
- Turn optional cleanup off and compare the baseline.
- Remove range, azimuth, value, and height filters.
- Select another elevation known to contain the variable.

If values are present but the colour scale is unsuitable, select **Auto by
variable** rather than imposing reflectivity limits on a different variable.

## Cleanup removes real signal

Turn **Remove noise, speckle and learned background clutter** off. Cleanup is an
optional in-memory view and cannot perfectly distinguish all weather,
biological echo, clutter, and receiver noise. Keep the baseline for scientific
interpretation and include settings in exported provenance.

## Animation pauses or blanks

Current packages keep the previous frame visible while the next frame loads and
preserve the map view. A first pass can still wait for uncached source objects;
the second pass should use the local caches. If a frame fails, the previous
frame remains visible and a warning identifies the failed time.

## An export does not appear

Desktop downloads go to the operating system's normal Downloads folder unless
the platform asks for another location. Use the export status and **View
Manifest** controls to confirm completion.

The export choices have different coordinate meanings:

- **Screen view PNG** matches the displayed map, legend, and annotations.
- **Polar PPI PNG or MP4** uses radar range-azimuth coordinates.
- **KMZ or GeoTIFF** is georeferenced for map or GIS use.
- **Raw source** downloads the selected HDF5 object for later analysis.

When reporting an export failure, include the requested format and the log.
