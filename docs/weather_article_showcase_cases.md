# Weather Article Showcase Cases

This page is draft text for the Weather article. It is written as a
manuscript-ready case-study section with figure placeholders to be replaced
after the final radar products are generated from a versioned catalog.

## Draft Article Text

The UK WSR Visualizer is most useful when a user can move directly from a
well-known weather event to the relevant radar, date, scan, and field. The
following cases were selected to span the main kinds of weather that a
quick-look radar tool should make accessible: short-lived urban convection,
persistent extreme rainfall, severe convective structures embedded in named
storms, frontal rainbands, and post-frontal showers in high-wind cyclones. The
suggested radar sites are not formal attribution of the event to a single
radar. They are practical starting points for reproducing figures in the app,
using the nearest or most informative UK weather surveillance radar coverage.

For the article figures, the primary field should usually be horizontal
reflectivity (`DBZH`) because it is interpretable across all cases. For
convective or tornadic examples, additional panels from radial velocity
(`VRADH`) and dual-polarisation fields such as correlation coefficient
(`RHOHV`), differential reflectivity (`ZDR`), and differential phase (`PHIDP`)
should be added where the selected source object contains those quantities.

### London convective flash flooding, July 2021

The July 2021 convective cases provide a compact example of why single-site
radar access matters for urban impacts. The Met Office monthly climate summary
describes the first twelve days of July as unsettled with heavy rain and
showers, especially over England, and records widespread weather impacts from
thunderstorms and rain warnings. On 12 July, the London Fire Brigade received
more than 1000 calls, with flooded properties, affected Underground and
overground rail lines, and wider road and bus disruption. Later in the month,
the 25 July diary entry notes locally heavy showers, thunderstorms in the
south-east, and localised flooding in some areas (Met Office, 2021).

For a radar showcase, `chenies` is the primary radar for Greater London, with
`thurnham` useful as a secondary perspective for Kent, Sussex, Essex, and the
Thames estuary. The figure should use a short time sequence around the
developing storms on 12 July and 25 July, with a map overlay showing the London
urban area and major transport corridors. This is the clearest case for showing
how the app supports fast visual triage of localised convective cells.

[Figure placeholder: London July 2021 convective flooding. Suggested panels:
`chenies` `DBZH` PPI time sequence for 20210712 and 20210725; optional
`thurnham` comparison panel for the south-east storm track; include map
labels for Greater London, the Thames, and major transport corridors.]

### Storm Babet, 18-21 October 2023

Storm Babet is the strongest persistent-rainfall case in this set. The Met
Office event summary reports exceptional rainfall in eastern Scotland, with
150 to 200 mm in the wettest areas, two red warnings for rain, and 19 October
2023 becoming the wettest day on record for Angus in a series from 1891. The
same report describes widespread heavy rain across England, Wales, and
Northern Ireland, with the England and Wales total over the event ranking as
the third-wettest independent three-day period in the 1891 series (Met Office,
2023a).

The app narrative should focus on slow-moving, high-coverage precipitation
rather than isolated convective peaks. `dudwick` is the preferred radar for
north-east Scotland and Angus, with `high-moorsley` useful for the northern
England rain shield and `munduff-hill` for Northern Ireland. A figure should
show several frames through 19 October and, if possible, a simple animation or
small multiple that highlights the persistence of high reflectivity over the
same catchments.

[Figure placeholder: Storm Babet persistent rainfall. Suggested panels:
`dudwick` `DBZH` at 20231019 0000, 0600, 1200, and 1800 UTC; optional
`high-moorsley` panel for the northern England rainband. Caption should note
that the figure shows radar structure, while rainfall totals and impacts are
cited from the Met Office event summary.]

### Storm Ciaran, 1-2 November 2023

Storm Ciaran demonstrates how the viewer can support high-impact coastal and
Channel-Islands cases. The Met Office describes the storm as exceptionally
severe for the time of year, with northern France and the Channel Islands
experiencing the strongest winds on the southern flank. The event summary also
notes a reported tornado affecting eastern Jersey, large hail, a Jersey Met
Service red warning, and significant damage and disruption across the Channel
Islands (Met Office, 2023b).

This case should be used to demonstrate multi-field inspection, not just a
reflectivity image. The primary radar is `jersey`, with `wardon-hill`,
`cobbacombe`, and `thurnham` available for the broader south-coast context. The
figure should show the late 1 November to early 2 November period and include
velocity or dual-polarisation panels if the final selected object contains
plot-ready fields.

[Figure placeholder: Storm Ciaran Jersey severe convection. Suggested panels:
`jersey` `DBZH`, `VRADH`, and one dual-pol field near the late-1-November
Jersey damage period; optional wider south-coast context from `wardon-hill` or
`cobbacombe`. Leave exact time stamps to be set after inspecting available
raw-volume times.]

### Storm Gerrit, 27-28 December 2023

Storm Gerrit is the best compact tornadic-rainband example. The Met Office
summary states that the storm brought damaging winds and heavy rain to the UK,
with Wales, north-west England, and Scotland worst affected, alongside heavy
snow in parts of Highland Scotland and a mini-tornado in Greater Manchester.
The same report identifies a rain-radar image at 2300 UTC on 27 December 2023
showing intense rainfall across the south Pennines near the Stalybridge
mini-tornado area (Met Office, 2023c).

For the app, this case should be framed around identifying the convective
feature in a national event. `hameldon-hill` is the first radar to test for
Greater Manchester, with `clee-hill` and `high-moorsley` as useful comparison
radars depending on data quality and range. The figure should pair a broader
reflectivity panel with a zoomed or filtered view around the south Pennines,
and should include radial velocity if the sweep geometry and quality are
suitable.

[Figure placeholder: Storm Gerrit south Pennines convective feature. Suggested
panels: `hameldon-hill` `DBZH` near 20231227 2300 UTC; optional `VRADH` panel
and comparison with `clee-hill` or `high-moorsley`. Caption should explicitly
separate radar-visible precipitation structure from the reported tornado
impact.]

### Storm Henk, 2 January 2024

Storm Henk is a broad frontal-rain and flood-impact case. The Met Office event
summary reports damaging winds and heavy rain across southern and central
England and Wales on 2 January 2024, with heavy rain contributing to major
flooding problems after an already wet autumn and December. The same summary
states that nearly 300 flood warnings were in place in England and includes a
rain-radar image at 1200 UTC showing heavy rain across much of Wales and
central England (Met Office, 2024a).

This example should show how users can choose between neighbouring radars for a
large synoptic feature. `clee-hill` is the key radar for the Severn and Welsh
border region, while `ingham`, `chenies`, and `deanhill` provide complementary
coverage for central and eastern England. A figure should show the rainband at
1200 UTC and, if possible, a short before/after sequence as the low crossed
southern Britain.

[Figure placeholder: Storm Henk frontal rainfall and flood context. Suggested
panels: `clee-hill` `DBZH` at 20240102 1200 UTC; optional `ingham` and
`chenies` panels to show the eastward extent. Include a map overlay for the
Severn, Midlands, and southern England.]

### Storm Bert, 22-25 November 2024

Storm Bert is a strong example of a multi-hazard storm where the radar story is
persistent rain. The Met Office summary reports that the weekend of 23-24
November 2024 was exceptionally wet across South Wales and south-west England,
with more than 150 mm in the wettest upland areas and the UK recording its
wettest calendar day, averaged across the whole country, since 3 October 2020.
It also notes severe flooding in Pontypridd from the River Taff and hundreds of
flooded properties in Wales and England (Met Office, 2024b).

The primary article figure should use `crug-y-gorrllwyn` for South Wales, with
`clee-hill` extending the view into western England and the Midlands. The event
is well suited to an animation or small multiple because the Met Office summary
uses six-hourly rain-radar imagery from 1200 UTC 23 November to 1800 UTC
24 November to illustrate the persistence and spatial extent of rainfall.

[Figure placeholder: Storm Bert South Wales and western England rainfall.
Suggested panels: `crug-y-gorrllwyn` `DBZH` at 20241123 1200 and 1800 UTC,
then 20241124 0000, 0600, 1200, and 1800 UTC; optional `clee-hill`
comparison. Caption should note Pontypridd/River Taff context using the Met
Office source.]

### Storm Darragh, 7 December 2024

Storm Darragh is a useful high-wind, heavy-rain communications case. The Met
Office named the storm on 5 December 2024, forecasting very strong winds and
heavy rain, then issued a red wind warning as the storm approached. On
7 December, the Met Office reported a red severe weather warning for western
and southern Wales and English counties around the Bristol Channel, observed
gusts of 93 mph at Capel Curig and 92 mph at Aberdaron, and an amber rain
warning for parts of South Wales where 80-90 mm of rain could fall during the
storm (Met Office, 2024c; 2024d; 2024e).

Radar cannot show the damaging wind directly, so this figure should be framed
around the precipitation structure accompanying the red-warning event.
`crug-y-gorrllwyn` is the primary radar for Wales, with `cobbacombe`,
`predannack`, and `clee-hill` useful for the Bristol Channel, south-west
England, and western Midlands. The final figure should make the limitation
explicit: the radar image demonstrates the rainband context, while the wind
gusts and warning status are cited from Met Office warning and news products.

[Figure placeholder: Storm Darragh red-warning context. Suggested panels:
`crug-y-gorrllwyn` `DBZH` during 20241207; optional `cobbacombe` or
`predannack` panel for the Bristol Channel and south-west England. Caption
should distinguish radar precipitation from wind impacts.]

### Storm Eowyn, 24 January 2025

Storm Eowyn is the best recent example of a very deep, high-impact cyclone. The
Met Office event summary describes it as the UK's most powerful wind storm for
over a decade, with Northern Ireland and Scotland's Central Belt experiencing
the strongest winds, a red warning for wind, widespread gusts above 70 kt, and
a UK maximum gust of 87 kt at Drumalbin, Lanarkshire. The report also notes
that the storm deepened explosively, with central pressure falling by 50 hPa in
24 hours, and that about a million homes were reported without power at the
storm's peak (Met Office, 2025).

For UK WSR Visualizer, this case is not a "wind field" plot; it should be used
to show the radar context of fronts and showers within a high-impact cyclone.
`castor-bay` and `munduff-hill` are the first choices for Northern Ireland,
while `druima-starraig`, `holehead`, and `dudwick` provide Scottish and
northern England perspectives. The best article figure is likely a regional
multi-radar comparison rather than a single-site close-up.

[Figure placeholder: Storm Eowyn fronts and showers in a high-impact windstorm.
Suggested panels: `castor-bay` or `munduff-hill` `DBZH` on 20250124, with a
comparison panel from `druima-starraig` or `holehead`. Caption should state
that wind impacts are from Met Office observations and warnings, while the app
figure shows radar-observed precipitation structure.]

## Case Selection Table

| Case | Date(s) for figure search | Primary radar(s) | Main field(s) | Article role |
| --- | --- | --- | --- | --- |
| London convective flooding | `20210712`, `20210725` | `chenies`, `thurnham` | `DBZH` | Localised urban convection |
| Storm Babet | `20231019`-`20231020` | `dudwick`, `high-moorsley`, `munduff-hill` | `DBZH` | Persistent extreme rainfall |
| Storm Ciaran | `20231101`-`20231102` | `jersey`, `wardon-hill`, `cobbacombe` | `DBZH`, `VRADH`, dual-pol | Channel-Islands severe convection |
| Storm Gerrit | `20231227`-`20231228` | `hameldon-hill`, `clee-hill`, `high-moorsley` | `DBZH`, `VRADH` | Tornadic rainband / embedded convection |
| Storm Henk | `20240102` | `clee-hill`, `ingham`, `chenies` | `DBZH` | Frontal rainfall and flooding |
| Storm Bert | `20241123`-`20241124` | `crug-y-gorrllwyn`, `clee-hill` | `DBZH` | Persistent South Wales/western England rain |
| Storm Darragh | `20241207` | `crug-y-gorrllwyn`, `cobbacombe`, `predannack` | `DBZH` | Red-warning wind event with rainband context |
| Storm Eowyn | `20250124` | `castor-bay`, `munduff-hill`, `druima-starraig` | `DBZH` | Deep cyclone fronts/showers context |

## Figure Production Notes

- Generate final figures from the exact catalog and software release cited in
  the article.
- Record radar slug, date, pulse, time, quantity, elevation/sweep, palette, and
  filters in every figure caption or supplementary table.
- Prefer `DBZH` for all overview panels; add `VRADH` and dual-pol fields only
  where the event and data quality make them interpretable.
- Use map overlays and range/azimuth filters consistently so figures are
  comparable across events.
- Keep wind-storm captions precise: UK WSR radar figures show precipitation
  structure, not the surface wind field.

## References

Met Office. 2021. *UK Monthly Climate Summary: July 2021*. Accessed
28 June 2026.
<https://www.metoffice.gov.uk/api/assets/file/uk_monthly_climate_summary_202107apdf?prefix=assets>

Met Office. 2023a. *Storm Babet, 18 to 21 October 2023*. Accessed
28 June 2026.
<https://www.metoffice.gov.uk/binaries/content/assets/metofficegovuk/pdf/weather/learn-about/uk-past-events/interesting/2023/2023_08_storm_babet.pdf>

Met Office. 2023b. *Storm Ciaran, 1 to 2 November 2023*. Accessed
28 June 2026.
<https://www.metoffice.gov.uk/binaries/content/assets/metofficegovuk/pdf/weather/learn-about/uk-past-events/interesting/2023/2023_09_storm_ciaran_2.pdf>

Met Office. 2023c. *Storm Gerrit, 27 to 28 December 2023*. Accessed
28 June 2026.
<https://www.metoffice.gov.uk/binaries/content/assets/metofficegovuk/pdf/weather/learn-about/uk-past-events/interesting/2023/2023_12_storm_gerrit.pdf>

Met Office. 2024a. *Storm Henk, 2 January 2024*. Accessed
28 June 2026.
<https://www.metoffice.gov.uk/binaries/content/assets/metofficegovuk/pdf/weather/learn-about/uk-past-events/interesting/2024/2024_01_storm_henk_v1.pdf>

Met Office. 2024b. *Storm Bert, 22 to 25 November 2024 and storm Conall,
26 to 27 November*. Accessed 28 June 2026.
<https://www.metoffice.gov.uk/binaries/content/assets/metofficegovuk/pdf/weather/learn-about/uk-past-events/interesting/2024/2024_09_storm_bert_v1.pdf>

Met Office. 2024c. *Storm Darragh has been named*. Published
5 December 2024. Accessed 28 June 2026.
<https://www.metoffice.gov.uk/about-us/news-and-media/media-centre/weather-and-climate-news/2024/storm-darragh-has-been-named>

Met Office. 2024d. *Red wind warning issued as Storm Darragh approaches*.
Published 6 December 2024. Accessed 28 June 2026.
<https://www.metoffice.gov.uk/about-us/news-and-media/media-centre/weather-and-climate-news/2024/red-warning-for-storm-darragh>

Met Office. 2024e. *Storm Darragh brings 90mph gusts and heavy rain*.
Published 7 December 2024. Accessed 28 June 2026.
<https://www.metoffice.gov.uk/about-us/news-and-media/media-centre/weather-and-climate-news/2024/storm-darragh-brings-90mph-gusts-and-heavy-rain>

Met Office. 2025. *Storm Eowyn, 24 January 2025*. Accessed
28 June 2026.
<https://www.metoffice.gov.uk/binaries/content/assets/metofficegovuk/pdf/weather/learn-about/uk-past-events/interesting/2025/2025_02_storm_eowyn.pdf>
