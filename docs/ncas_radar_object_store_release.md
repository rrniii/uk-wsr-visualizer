# Object Store Release History

> **Historical maintainer record.** This page distinguishes completed migration
> milestones from the current public state. It is not a live operations log.

## Current state

The public PVOL catalogue at
`ukmo-nimrod/catalog/pvol/catalog.json` is the desktop application's default
source. The snapshot generated on 23 July 2026 reports:

- `upload_complete: true`;
- 17 radar sites;
- 58,427 radar-days;
- 23,557,040 files;
- 132.4 TB represented;
- coverage through 21 July 2026.

The catalogue and HDF5 objects are readable over public HTTPS without user
credentials. Desktop access remains lazy: the client loads only selected
coverage/day metadata and source volumes.

## Superseded rehearsal

In June 2026, a Chenies 2018 subset was used to rehearse:

- catalogue and STAC creation;
- checksum and manifest generation;
- CORS;
- staged upload and verification;
- public status records;
- client smoke tests.

That subset and its transfer pauses were migration history. They do not describe
the current collection and must not be used as the public coverage statement.

## Release checks

For every future catalogue refresh:

1. Verify the root schema and `upload_complete` state.
2. Confirm all radar-year coverage keys are readable.
3. Sample day catalogues across sites and years.
4. Confirm sample HDF5 size/checksum records.
5. Check coordinates for all radar sites.
6. Confirm no private source paths or credentials are published.
7. Test external CORS and object reads.
8. Launch a desktop client with an empty cache and render a sample PPI.
9. Record the generated time, counts, coverage range, and source commit.

Do not describe a refresh as complete until those checks pass.
