# Data and Radar Terms

UK WSR Visualizer is designed to be usable before you become a radar-data
specialist. This page explains the terms used by the app and by the published
catalogue.

## From the archive to the app

The UK weather-surveillance radar record is held by CEDA. On JASMIN, source
material is converted and checked, then published as individual ODIM PVOL HDF5
objects with lightweight JSON catalogues. The app reads the catalogues first
and downloads only the selected volume.

The public Object Store is an access mirror, not the authoritative archive and
not a replacement citation for the source dataset.

## Radar geometry

**Radar site**
: A single transmitting and receiving installation, such as Castor Bay or
  Chenies. Each site has a latitude, longitude, and antenna height.

**Volume (PVOL)**
: A set of scans made at several antenna elevation angles around one time. One
  public HDF5 object represents one site, pulse, and nominal time.

**PPI**
: Plan Position Indicator. A two-dimensional view of one sweep, plotted by
  azimuth and distance from the radar and georeferenced over a map in the
  desktop viewer.

**Sweep or elevation**
: One rotation of the antenna at a nominal elevation angle. The example Castor
  Bay volume used in this guide contains sweeps at 0.50, 0.95, 2.00, 3.00, and
  4.00 degrees.

**Ray**
: Data recorded along one antenna azimuth.

**Gate or bin**
: One sampled distance interval along a ray. A radar value belongs to a gate,
  not to an exact point at ground level.

**Beam height**
: An estimate of the height of the radar beam at a selected range. It increases
  with both range and elevation angle and is not the same as terrain height.

## Pulse and time

**Long pulse (lp)**
: A pulse configuration generally used for longer-range coverage. It is shown
  as a separate source choice because its sampling and range can differ from
  short pulse.

**Short pulse (sp)**
: A pulse configuration generally used for finer near-range sampling. Not every
  day or time contains both pulse types.

Times are UTC and are written as four digits in the catalogue and controls.
For example, 1535 means 15:35 UTC. Dates use YYYY-MM-DD in the app and YYYYMMDD
in command-line selectors and catalogue records.

## Common variables

The app presents a descriptive name followed by the ODIM quantity code where
space permits.

| Descriptive name | ODIM code | What it represents |
|---|---|---|
| Horizontal Reflectivity | DBZH | Returned horizontal radar power on a logarithmic dBZ scale. |
| Horizontal Radial Velocity | VRADH | Motion towards or away from the radar in metres per second. |
| Horizontal Spectrum Width | WRADH | Spread of radial velocities within a gate. |
| Differential Reflectivity | ZDR | Difference between horizontal and vertical reflectivity. |
| Copolar Correlation Coefficient | RHOHV | Similarity of horizontal and vertical returns. |
| Differential Phase | PHIDP | Accumulated phase difference between horizontal and vertical signals. |
| Specific Differential Phase | KDP | Range derivative of differential phase. |
| Signal Quality Index | SQIH | A signal-quality indicator supplied in the source volume. |

Availability varies with radar, date, pulse, time, and elevation. The app only
offers combinations present in the selected volume.

## Data eras

The desktop selector keeps the dual-polarisation and pre-dual-polarisation
catalogues separate. The public dual-polarisation PVOL catalogue is the default.
A pre-dual-polarisation catalogue must be configured explicitly; if it is not
available, the app retains the current selection and reports the problem rather
than silently substituting another era.

## Missing and filtered values

Source nodata and undetect codes are decoded as missing values. Optional display
cleanup is performed in memory and never overwrites the HDF5 source object.
Because weak weather, biological echoes, noise, and clutter can overlap in the
available variables, cleanup output must be treated as a reproducible
interpretive view, not as infallible classification.

For scientific work, compare the cleaned view with the baseline and record the
settings in the export manifest.
