# Citing UK WSR Visualizer

If UK WSR Visualizer is used to produce a figure, export, derived object, case selection, or research result, cite all relevant credit objects:

1. the archived software release used in the analysis;
2. the accompanying Weather article when available;
3. the formal source-data citation for the UK weather surveillance radar data used;
4. JASMIN, where JASMIN storage or compute was used.

## Software citation

Use the Zenodo DOI for the exact release used in the analysis. Until the first Zenodo release is minted, use:

> Neely, R. R. III. UK WSR Visualizer, version 0.1.0. GitHub. https://github.com/rrniii/uk-wsr-visualizer

After the first Zenodo archive, replace this with the release DOI.

## Article citation

The companion article is in preparation:

> Neely, R. R. III. UK WSR Visualizer: community access and visualisation to UK weather surveillance radar data. Weather. DOI: TODO.

After publication, cite the article for the community-access rationale and the software DOI for exact-version reproducibility.

## Source-data citation

Do not replace the source-data citation with a generic radar-data citation. Use the formal citation agreed with the data owner and archive for the UK WSR aggregate HDF5 source objects used in the analysis.

TODO: Insert the final source-data citation and licence/access statement here.

## JASMIN acknowledgement

Where JASMIN storage or compute contributed to the workflow, include:

> This work used JASMIN, the UK's collaborative data analysis environment.

## Command-line citation output

```bash
uk-wsr-visualizer citation
uk-wsr-visualizer citation --json
```

The JSON form is intended for automated export manifests and provenance capture.
