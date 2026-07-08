UK WSR Visualizer Linux beta
============================

This is a portable Linux beta for Ubuntu 22.04, Ubuntu 24.04, and Debian 12.

Run
---

AppImage:

  chmod +x "UK WSR Visualizer Linux.AppImage"
  ./UK\ WSR\ Visualizer\ Linux.AppImage

Portable tarball:

  tar -xzf "UK WSR Visualizer Linux portable.tar.gz"
  cd "UK WSR Visualizer"
  ./UK\ WSR\ Visualizer

The app opens its own Qt window. It starts a bundled local Python/FastAPI
server and loads the radar interface from 127.0.0.1. It does not require a
system Python installation when using the packaged beta.

Runtime files
-------------

Cache:

  $XDG_CACHE_HOME/uk-wsr-visualizer/data
  or ~/.cache/uk-wsr-visualizer/data

Logs:

  $XDG_STATE_HOME/uk-wsr-visualizer/uk-wsr-visualizer.log
  or ~/.local/state/uk-wsr-visualizer/uk-wsr-visualizer.log

Self-test
---------

  ./UK\ WSR\ Visualizer --self-test

The self-test starts the bundled server, waits for /api/ready, prints
/api/status, and shuts down without opening a visible app window.

If the app does not start, send the log file and the radar/date/variable/time
you were trying to use.
