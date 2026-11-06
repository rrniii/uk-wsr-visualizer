# How the app fits together

The apps share catalogue, selection and export formats. Their interfaces remain
native to each platform.

## Desktop

The native shell starts a private FastAPI server on loopback and opens the
viewer in its own window. The packaged server includes Python, scientific
libraries, QC and the video encoder.

`CatalogService` owns archive selection, lazy root/year/day metadata, source
hydration and prefetch. API routes use this service rather than keeping separate
catalogue state. Readiness does not require a working remote catalogue.

Catalogue records, HDF5 inspection and PVOL JSON decoding are separate modules.
The existing `catalog` imports remain available to callers. The API owns its
short-lived rendered-frame cache; changing archive era clears that cache too.

The viewer's scripts load in the order listed in `static/index.html`. A panel
request takes ownership before hydration. Only that request may commit a frame,
show an error or clear its loading state. Animation and cache hits use the same
frame commit path.

## Mobile

The iOS view model owns selection and loading state. Views show controls and
results; export coordination, location, recent selections and map snapshots have
separate owners. Android follows the same data flow using Kotlin and Compose.

Both mobile apps use the shared C reader to inspect and decode a cached HDF5
file. Platform code owns file download, UI state and export. The decoder keeps
measured values, NODATA, UNDETECT and ray geometry distinct. Rendering or cleanup
must not change the original file.

## Keep these contracts

- A selection identifies the source, radar, UTC time, pulse, quantity and sweep.
- A late response must not replace a newer selection or its error state.
- Missing data remain missing. Cached views must retain their actual identity.
- Projects and exports record display settings, cleanup and build provenance.
- Desktop QC stays pinned. Porting a platform does not approve a research model.

Add a comment when a rule is easy to break: explain the reason, units or edge
case. Names and small functions should explain the routine work.
