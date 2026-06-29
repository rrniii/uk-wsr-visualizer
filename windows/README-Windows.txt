UK WSR Visualizer Windows Beta
==============================

Run
---

1. Extract the zip file.
2. Double-click "UK WSR Visualizer.exe".
3. Wait on the radar logo while the local server starts.

The app opens its own Windows window. It does not require Python to be
installed and it does not open your default browser.

Data
----

The app connects to the public JASMIN Object Store catalog:

https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json

Selected radar source files are downloaded only when needed and cached under:

%LOCALAPPDATA%\UK WSR Visualizer\data\remote-aggregate-cache

Basic workflow
--------------

1. Enter a date or date range.
2. Choose one of the available radars.
3. Select a source item, variable, time, and elevation.
4. Use the mouse wheel to zoom, drag to pan, and click the PPI for a value
   readout.
5. Use "Export & Provenance" to create a PNG quick-look or metadata JSON export
   with an artifact manifest.

Logs
----

If the app does not start, send this log file with the bug report:

%LOCALAPPDATA%\UK WSR Visualizer\uk-wsr-visualizer.log

WebView2
--------

Windows needs the Microsoft Edge WebView2 Runtime. Most Windows 10/11 systems
already include it. If the app reports that WebView2 is missing, install the
Evergreen WebView2 Runtime from Microsoft:

https://developer.microsoft.com/microsoft-edge/webview2/
