# Viewer

The viewer renders one sweep from one single-site radar volume over a map. Its
controls are constrained by the selected source so that an unavailable
time-variable-elevation combination cannot be requested.

## Data selection

Use a date-first workflow:

1. Choose the **Data era**.
2. Enter start and end dates as YYYY-MM-DD.
3. Select one of the enabled radars.
4. Choose a pulse, or leave **Any** while discovering a day.
5. Press **Search Catalogue** and select an item.

The public dual-polarisation catalogue is the default. Pre-dual-polarisation
data require a separately configured catalogue. The app does not silently
substitute one era for the other.

Selecting a different radar recentres the first new plot on that site's
coordinates. Later time, variable, and elevation changes preserve the user's
zoom and pan; **Fit View** explicitly resets the extent.

## Radar controls

After a source is selected, choose:

- a descriptive variable, with its ODIM code;
- a four-digit UTC time;
- a sweep/elevation angle;
- opacity and, under Advanced, a palette and physical display limits.

The app reports the displayed sweep and nominal elevation in the plot label.
The pointer can show value, range, beam height, elevation, latitude/longitude,
and source bin. Disable unneeded pointer fields to keep compact panels clear.

## Maps and navigation

Use mouse wheel or trackpad zoom, drag to pan, double-click to zoom, and touch
pan/pinch where supported. Basemap tiles, range rings, and labels are static
layers; changing a radar frame does not rebuild them unnecessarily.

Range rings describe distance from the radar, not administrative boundaries or
data validity.

## Optional cleanup

The Advanced section contains **Remove noise, speckle and learned background
clutter**. It applies versioned QC logic in memory and never changes the source
HDF5 object.

Start a scientific inspection with cleanup off, then compare the optional
result. No gate-level method can guarantee removal of every nuisance echo while
retaining all weak weather and biological signal. If the cleaned result removes
plausible signal, keep the baseline and report the case.

Cleanup settings and version information are included in export provenance.
The algorithm and validation evidence are maintained in the separate,
versioned `uk-wsr-qc` project.

## Animation

Previous and next controls step through valid times. Playback prefetches nearby
frames and keeps the current frame visible while the next frame loads. The map
view remains fixed unless **Fit View** is pressed.

The first pass may still wait for source downloads. Cached replay should be
faster. A failed frame leaves the previous frame visible and reports the time
that failed.

## Four-panel comparison

Each panel has independent item, variable, time, and elevation state. Link
controls determine what should move together:

- **View** links zoom and pan.
- **Time** steps all panels to their nearest valid shared time.
- **Variable** intentionally makes all panels use the same variable.
- **Elevation** matches by physical elevation angle, not dataset number.

Leave variable and elevation links off when comparing different moments or
heights. Changing one panel must not reset another panel's independent
elevation.

Each panel retains its own palette and display limits. Enable colour-scale
linking only when a common physical scale is meaningful; leave it off when
comparing variables with different units or expected ranges.

## Recent selections

Successful selections are stored on the local device and shown at the bottom of
the sidebar. They contain selection metadata, not radar arrays, and can be
cleared without changing the source cache.

## Cache

Raw source objects are stored in a disposable, least-recently-used cache. The
default maximum is 25 GB and there is no age expiry. Catalogue metadata and
rendered frames use separate smaller caches.

Use **Clear Raw Cache** to remove local HDF5 copies. The next use downloads the
source again.
