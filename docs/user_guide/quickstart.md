# Quick Start

This walkthrough uses a verified public source object:

| Selection | Value |
|---|---|
| Radar | Castor Bay (07) |
| Date | 18 September 2014 |
| Pulse | Long pulse (lp) |
| Time | 15:35 UTC |
| Variable | Horizontal Reflectivity (DBZH) |
| First elevation | 0.50 degrees |

The day catalogue contains 101 long-pulse volumes from 15:35 through 23:55
UTC. The 15:35 volume contains eight variables across five sweeps at 0.50,
0.95, 2.00, 3.00, and 4.00 degrees.

## First plot in the desktop app

1. Start UK WSR Visualizer and wait for **Catalogue loaded**.
2. Keep **Dual-polarisation era** selected.
3. Enter `2014-09-18` for both start and end date.
4. Select **Castor Bay (07)** and **Long pulse (lp)**.
5. Press **Search Catalogue**.
6. Select the Castor Bay item, time **1535**, **Horizontal Reflectivity
   (DBZH)**, and elevation **0.50 degrees**.
7. Leave the optional cleanup off for the first inspection.
8. Use **Fit View**, then zoom and pan without changing the source selection.
9. Click a gate to read its value, range, beam height, elevation, and location.

The first plot can take longer because the app downloads a 6.6 MB HDF5 source
object and scans it. Repeating the selection uses the local caches.

## Inspect the source

**Source URL** opens or copies the public object URL. **Open Source** downloads
the selected HDF5 object for analysis. The app does not modify that source.

The example object is:

~~~text
ukmo-nimrod/pvol/castor-bay/2014/09/18/lp/
20140918_polar_pl_radar07_aggregate_lp_1535.h5
~~~

## Compare before interpreting

1. Step from 1535 to 1540 with **Next Time**.
2. Change from 0.50 to 0.95 degrees and note the beam-height change.
3. Switch to **4 Panel**.
4. Compare two times and two elevations while keeping the map view linked.
5. Keep variable and elevation links off when panels should remain independent.

See [Four-panel comparison](../example_gallery/four_panel.md) for a controlled
layout.

## Export evidence

Choose **Metadata JSON + manifest** for the smallest provenance example or
**Screen view PNG** for a figure matching the current map. After completion,
open **View Manifest** and confirm:

- software version and commit;
- radar, date, pulse, time, variable, and elevation;
- source object key and URL;
- coordinate mode;
- display and cleanup settings;
- software, article, source-data, and JASMIN citation fields.

## Reproduce the preview from source

The [First look from one public volume](../example_gallery/first_look.md)
example downloads this same HDF5 object, builds a one-item local catalogue, and
generates a preview with tested commands.
