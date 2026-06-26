# Citation

If you use UK WSR Visualizer to produce a figure, export, derived object, case selection, or research result, cite four distinct credit layers.

## 1. Software release

Cite the exact archived software release used in your analysis. After the first tagged release is archived on Zenodo, replace the placeholder below with the Zenodo DOI.

> Neely, R. R. III. UK WSR Visualizer, version 0.1.0. Zenodo. DOI: TBD.

## 2. Weather article

After publication, cite the accompanying article:

> Neely, R. R. III. UK WSR Visualizer: community access and visualisation to UK weather surveillance radar data. Weather. DOI: TBD.

## 3. Source data

Cite the formal source-data record for the UK WSR aggregate HDF5 data used in your analysis.

> TODO: Insert the formal UK WSR aggregate HDF5 source-data citation agreed with the data owner and archive. Do not substitute a citation for a different data product family.

## 4. JASMIN acknowledgement

Where the work used JASMIN storage or compute, include:

> This work used JASMIN, the UK's collaborative data analysis environment.

## Recommended methods wording

> UK weather surveillance radar data were inspected using UK WSR Visualizer v0.1.0 (software DOI: TBD). The source data were obtained from [formal source-data record and citation]. This work used JASMIN, the UK's collaborative data analysis environment.

The command-line citation helper prints the current citation block:

```bash
uk-wsr-visualizer-citation
uk-wsr-visualizer-citation --json
```
