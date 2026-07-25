# Linux Install And Use

The Linux beta is a native Qt desktop wrapper around the same UK WSR Visualizer
server and web interface used by the Mac and Windows apps. It is intended for
Ubuntu 22.04, Ubuntu 24.04, and Debian 12. It also includes a software-rendering
fallback for enterprise Linux desktops such as Rocky Linux 9 or RHEL 9 where
Qt WebEngine can otherwise open a blank or flickering white window on some
NVIDIA, Wayland, or virtual-machine display stacks.

## Download

Use the Linux beta artifact from the release or workflow build:

```text
UK WSR Visualizer Linux.AppImage
UK WSR Visualizer Linux portable.tar.gz
```

The AppImage is the simplest route for most testers. The portable tarball is
useful when AppImage support is restricted on a managed Linux desktop.

## Run The AppImage

```bash
chmod +x "UK WSR Visualizer Linux.AppImage"
./UK\ WSR\ Visualizer\ Linux.AppImage
```

## Run The Portable Tarball

```bash
tar -xzf "UK WSR Visualizer Linux portable.tar.gz"
cd "UK WSR Visualizer"
./UK\ WSR\ Visualizer
```

The app starts a bundled local server, shows the logo while it becomes ready,
and then opens the radar viewer in its own Qt window.

## Blank Or Flickering Window

If the app starts but the radar interface is blank, restart it with CPU
software rendering:

```bash
./UK\ WSR\ Visualizer --software-rendering
```

The equivalent environment setting is:

```bash
UK_WSR_VISUALIZER_LINUX_RENDERER=software ./UK\ WSR\ Visualizer
```

Renderer modes are `auto`, `software`, and `hardware`. The default `auto` mode
keeps normal Qt WebEngine rendering on common Ubuntu/Debian desktops but
selects software rendering automatically on Rocky/RHEL-like systems and likely
VM/NVIDIA/Wayland problem cases.

## Cache And Logs

The Linux app follows the XDG directory conventions.

Cache:

```text
$XDG_CACHE_HOME/uk-wsr-visualizer/data
~/.cache/uk-wsr-visualizer/data
```

Log:

```text
$XDG_STATE_HOME/uk-wsr-visualizer/uk-wsr-visualizer.log
~/.local/state/uk-wsr-visualizer/uk-wsr-visualizer.log
```

If startup or data loading fails, send the log file with the radar, date,
time, variable, and elevation you were trying to load.

## Self-Test

From the extracted tarball:

```bash
./UK\ WSR\ Visualizer --self-test
```

The self-test starts the bundled server, waits for `/api/ready`, prints
`/api/status`, and exits without opening the window.

## Build From Source

On Linux:

```bash
git clone git@github.com:rrniii/uk-wsr-qc.git
git clone git@github.com:rrniii/uk-wsr-visualizer.git
cd uk-wsr-visualizer
python -m venv .venv
. .venv/bin/activate
pip install -e ../uk-wsr-qc
pip install -e ".[dev,video,linux]"
linux/build.sh
```

The build writes artifacts under:

```text
build/linux-beta/
```
