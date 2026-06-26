# Citation and attribution

UK WSR Visualizer separates software credit, article credit, source-data credit, and infrastructure acknowledgement.

If the tool is used to produce a figure, export, derived object, case selection, or research result, cite the following.

## Software release

Cite the exact archived software release used in the analysis. After the first tagged release is archived on Zenodo, replace the placeholder with the versioned software DOI.

> Neely, R. R. III. UK WSR Visualizer, version 0.1.0. Zenodo. DOI: TBD.

## Weather article

After publication, cite the accompanying article.

> Neely, R. R. III. UK WSR Visualizer: community access and visualisation to UK weather surveillance radar data. Weather. DOI: TBD.

## Source data

Cite the formal source-data record for the UK WSR aggregate HDF5 data used in the analysis.

> TODO: Insert the formal UK WSR aggregate HDF5 source-data citation agreed with the data owner and archive.

Do not substitute a citation for a different data product family.

## JASMIN acknowledgement

Where the work used JASMIN storage or compute, include:

> This work used JASMIN, the UK's collaborative data analysis environment.

## Citation helper

The installed package provides a citation helper:

```bash
uk-wsr-visualizer-citation
uk-wsr-visualizer-citation --json
```

Exports write citation and provenance metadata into `artifact-manifest.json` so users can recover the software version, source object, source-data citation placeholder, and JASMIN acknowledgement from generated artifacts.
