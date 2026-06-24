# UK Radar Ground-Mapping Practical

This note translates the Lecture 6 R practical outline from
`Lecture6-Mapping_animals_to_the_ground.pptx` into Python for UK WSR
aggregates.

The deck does not contain embedded R source code. The translation below follows
the practical structure listed on slide 3:

1. set up libraries, constants, and functions
2. create a polygon-based basegrid
3. determine ground heights underneath sampling volumes
4. compute topographic beam blockage
5. estimate beam propagation using radiosonde data

## Python Equivalents

| Lecture R practical part | Python location | UK radar adaptation |
| --- | --- | --- |
| Setup libraries/constants/functions | `src/uk_wsr_visualizer/ground_mapping.py` | Uses existing UK WSR Visualizer `RadarGridMetadata` and optional `rasterio` for DEM sampling. |
| Create `basegrid` | `make_radar_sample_grid()` | Builds a radar-centred polar grid from a UK WSR aggregate field, with azimuth/range centres, lon/lat, and cell area in hectares. |
| Ground heights under sampling volumes | `sample_dem_at_grid()` | Samples any raster DEM readable by `rasterio`; if no DEM is available, the example script can use a constant terrain height for testing. |
| Topographic beam blockage | `topographic_blockage_fraction()` | Computes local circular-beam blockage and accumulates the maximum blockage along each radial, matching the common "mask >25%" workflow. |
| Beam propagation from radiosonde | `refractivity_gradient_n_per_km()` and `effective_earth_radius_factor_from_gradient()` | Reads pressure, temperature, dewpoint, and height from a sounding CSV and replaces the standard 4/3 earth beam path. |
| VPR / beam overshoot support | `vertical_profile_detection_fraction()` | Computes the fraction of a supplied vertical profile sampled by the beam at each grid cell. |

## Run The Practical

Install the package with export dependencies when DEM sampling is needed:

```bash
pip install -e ".[export]"
```

Run on a single UK aggregate field:

```bash
python examples/uk_radar_ground_mapping_practical.py \
  --aggregate /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site/thurnham/2024/20241001_polar_pl_radar20_aggregate.h5 \
  --radar thurnham \
  --date 20241001 \
  --pulse lp \
  --time 2100 \
  --quantity DBZH \
  --dataset dataset1 \
  --dem /path/to/uk_dem.tif \
  --max-range-km 100 \
  --range-step-km 1 \
  --azimuth-step-deg 1 \
  --output-csv outputs/thurnham_20241001_ground_mapping.csv \
  --summary-json outputs/thurnham_20241001_ground_mapping_summary.json
```

For propagation from a sounding, add:

```bash
  --sounding-csv /path/to/sounding.csv
```

The sounding CSV must contain:

```text
height_m,pressure_hpa,temperature_c,dewpoint_c
```

The output CSV has one row per radar grid cell:

- `azimuth_deg`
- `range_km`
- `longitude`
- `latitude`
- `cell_area_ha`
- `terrain_m_asl`
- `beam_center_m_asl`
- `ground_clearance_m`
- `topographic_blockage_fraction`
- `mask_blockage_gt_25pct`

## Applying To Biological Radar Products

The lecture's biological mapping logic sits downstream of this ground-mapping
step:

1. Use the existing UK WSR aggregate pipeline to obtain UK single-site HDF5.
2. Use this practical to build terrain, blockage, and beam-height masks.
3. Use the JASMIN BioDAR/bioRad or `vol2bird` workflow to derive biological
   profiles and migration quantities.
4. Combine the VPR fraction with reflectivity products to reduce range bias and
   mask overshoot, following the lecture's VPR/VIZ/VIR logic.

The script intentionally writes a plain CSV so the basegrid can be joined to
land cover, coast distance, light-at-night, protected areas, or model covariates
without requiring a specific geospatial dataframe stack.
