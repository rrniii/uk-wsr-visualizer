# Public Data and the Object Store

Normal desktop use requires no object-store credentials. The app reads public
HTTPS catalogue records and downloads only the selected source volume.

## Data path

~~~text
CEDA archive
  -> JASMIN conversion and integrity checks
  -> per-volume ODIM PVOL HDF5 objects
  -> lazy JSON catalogues
  -> public JASMIN Object Store
  -> local desktop cache
~~~

CEDA remains authoritative. The Object Store is a public access mirror prepared
for efficient discovery and selected-volume retrieval.

## Current public snapshot

The final PVOL catalogue snapshot generated on 23 July 2026 reports:

- 17 radar sites;
- 58,427 radar-days;
- 23,557,040 per-volume HDF5 objects;
- 132.4 TB represented;
- coverage from 21 January 2013 through 21 July 2026;
- `upload_complete: true`.

These counts are dated inventory values. A later catalogue may contain more
data. A missing public date is not proof that no source exists in CEDA.

## Lazy discovery

The app reads the root once, then only the selected radar-year coverage record
and day catalogue. It does not load approximately 23.6 million file records at
startup.

Radar site coordinates are in the root catalogue and support map overlays and
nearest-site behavior without opening day records. Optional field indexes can
provide variable and elevation metadata; missing indexes fall back to scanning
the chosen HDF5 object.

## Local data

Downloaded HDF5 files are unchanged copies of public source objects. The
default raw cache is bounded to 25 GB with least-recently-used eviction and can
be cleared from the app. User exports remain local unless the user shares them.

## Maintainer publication

Credentials, bucket configuration, checksum verification, CORS, and promotion
belong to [Maintainer Operations](../operations/index.md). Do not put
credentials in this repository or publish source objects outside the approved
data policy.
