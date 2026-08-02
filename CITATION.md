# Citation

If UK WSR Visualizer is used to produce a figure, export, derived object, case selection, or research result, cite four distinct credit layers.

## 1. Software release

Cite the exact archived software release used in the analysis. The DOI is pending until a versioned archive has been minted.

> Neely, R. R. III. UK WSR Visualizer, version 0.2.2. Zenodo. DOI: pending.

## 2. Weather article

After publication, cite the accompanying article:

> Neely, R. R. III. UK WSR Visualizer: community access and visualisation to UK weather surveillance radar data. Weather. DOI: pending.

## 3. Source data

Cite the formal source-data record for the UK WSR archive data represented by
the published per-volume PVOL HDF5 objects used in the analysis.

> Formal UK WSR source-data citation pending. Do not substitute a citation for
> a different data product family, and do not cite the object-store mirror as
> the authoritative source-data record.

## 4. JASMIN acknowledgement

Where the work used JASMIN storage or compute, include:

> This work used JASMIN, the UK's collaborative data analysis environment.

## Recommended methods wording

> UK weather surveillance radar data were inspected using UK WSR Visualizer
> v0.2.2 (software DOI pending). The selected per-volume PVOL HDF5 access
> object and its formal UK WSR source-data record were retained in the analysis
> provenance. This work used JASMIN, the UK's collaborative data analysis
> environment.

The command-line citation helper prints the current citation block:

```bash
uk-wsr-visualizer-citation
uk-wsr-visualizer-citation --json
```
