# Cross-platform behaviour

Desktop uses the shared Python/API viewer. iPhone and iPad use SwiftUI;
Android uses Kotlin and Compose. Mobile apps decode cached HDF5 files on device.

Equivalent selections must identify the same source, radar, UTC time, pulse,
quantity and sweep. Every export needs enough settings and build information to
reproduce it. No viewer operation may change a source file.

## Shared workflow

- Load the public catalogue lazily, then fetch the selected source object.
- Select radar, date, pulse, variable, time and elevation.
- Show a georeferenced PPI with pan, zoom, value lookup and a labelled scale.
- Step through time, play an animation and restore recent selections.
- Compare panels with explicit links for time, view, variable and elevation.
- Save and restore projects; export PNG and MP4 with provenance.
- Inspect source/citation details and clear the local raw cache.

Missing times must remain unavailable. A late request must not overwrite a
newer selection. A retained frame must keep its original label.

## Processing and display

Keep the decoded baseline available. Cleanup is an optional, reversible display
choice; its settings belong in project files and export manifests. Desktop QC
stays pinned to the supported runtime. Mobile processing must state its actual
method and supported options rather than imply desktop algorithm parity.

NODATA, UNDETECT and measured values remain distinct in the decoder. Use source
ray angles and gate spacing, including azimuth wrap and range offset.

Keep normal selection and navigation controls visible. Put specialist filters,
manual colour limits and processing diagnostics under **Advanced**. Short labels
should explain the choice; tooltips can explain units and edge cases.

## Platform differences

Desktop provides extra export formats, including KMZ, GeoTIFF and NetCDF, and
uses native WebKit, WebView2 or Qt shells. Each package includes its Python
runtime, QC and MP4 encoder. Normal use must work without Python on `PATH`.

iOS uses MapKit and native sharing. Android uses a native map view with
OpenStreetMap tiles and Android sharing.
Device permissions, local storage and background work follow the platform's
normal controls. A built mobile archive is not evidence of store availability.

## Verify the delivered build

Exercise selection, baseline/cleanup, interaction, four panels, projects,
PNG/MP4, cache clearing and provenance. Use real public source files as well as
small deterministic fixtures. Hash sources before and after.

For desktop, run the native launcher and packaged server without an external
Python installation. Check the declared minimum OS and all included encoders.
For mobile, test phone and tablet layouts, ray geometry, sentinel handling,
sharing and offline/error recovery. Record simulator/emulator checks separately
from physical-device checks.

Record the exact build, checksums and limitations with the artifacts. Verify
TestFlight or Google Play processing and tester assignment only when publishing.
