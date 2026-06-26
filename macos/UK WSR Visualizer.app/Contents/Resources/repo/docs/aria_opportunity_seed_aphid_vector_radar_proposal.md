# ARIA Opportunity Seed Draft

## Proposal Title

Aerial BioScope: a dual-band vertical radar for aphid and agricultural vector flux

## Part 1: Proposal Narrative

### 1. Proposed activity

This proposal seeks to build and field-test a compact, vertically looking, dual-band W-band and Ka-band radar station for measuring aphid-sized airborne insect flux above crops. The system is intended to create a new class of agricultural biosphere sensor: a farm-deployable instrument that reports the arrival, height distribution, movement and confidence of vector-sized insects before crop symptoms or conventional trap counts provide sufficient warning.

The starting point is a measurement gap in agriculture and Earth-system sensing. Operational monitoring is strong for weather, rainfall, aerosols and some forms of crop condition, yet it remains weak for the biological material moving through the lower atmosphere. Aphids are an appropriate first target because winged aphids are among the most important insect vectors of plant viruses, including systems affecting cereals, potatoes, sugar beet, brassicas and horticultural crops. For many non-persistent viruses, the damaging event can occur during brief probing by a winged migrant rather than after a visible colony has established. Monitoring that only sees insects after they enter a trap, land on a plant or generate disease symptoms is therefore structurally late for many disease-risk decisions.

The proposed instrument combines three design traditions:

- the UK vertical-looking radar tradition, which demonstrated that autonomous zenith-pointing radar can quantify insect migration aloft and extract target size, shape, alignment and displacement;
- Australian radar-entomology field practice, which emphasised robust unattended deployments and the connection between weather, migration and agricultural pest risk;
- compact crop-monitoring station designs, including Wuxi-style integrated pest stations, which point toward practical farm deployments combining sensing, weather, traps, telemetry and automated alerts.

The technical advance is to push vertical-looking radar toward smaller vector-sized targets by using 94 GHz W-band as the primary aphid-sensitive channel and 35 GHz Ka-band as a colocated confirmation, attenuation, rain and larger-target context channel. The system will not claim direct radar taxonomy or species identification. It will instead produce a validated probabilistic data product: vector-sized aerial activity by height, time and weather context, with trap-confirmed labels and explicit uncertainty.

The seed project will produce five outputs:

1. a working dual-band vertical radar prototype for crop-edge or field-centre deployment;
2. a labelled field dataset linking W-band and Ka-band radar features to aphid traps, camera observations, crop state and weather;
3. an open processing pipeline for range-Doppler, dual-band ratio, polarimetric where available, micro-Doppler and quality-control features;
4. a first aphid/vector influx index for use by plant pathologists, agronomists, crop disease models and integrated pest management services;
5. a technical and commercial design package for a follow-on network of agricultural biosphere observatories.

### 2. Scientific and technological importance

This is a missing measurement layer for ARIA's Scoping Our Planet opportunity space. The opportunity space is concerned with closing Earth-system measurement and modelling gaps using frontier sensors, platforms and AI-enabled interpretation. Aerial insects form part of that system. They move biomass, nutrients, genes, crop pests, pathogens and beneficial services across landscapes. Radar studies over southern Britain have shown that trillions of high-flying insects and thousands of tonnes of biomass can move through the air column seasonally. However, these measurements were not designed as operational agricultural vector observatories, and existing weather radars cannot resolve aphid-scale targets at farm decision scales.

#### Why aphids require better monitoring

Aphids matter because they combine five properties that make them difficult and commercially important agricultural targets.

First, aphids are disease vectors as well as direct pests. They damage crops through phloem feeding, honeydew, sooty mould, plant stress and yield reduction, but their greatest system-level importance often comes from virus transmission. Aphid-vector interactions underpin major crop-virus systems, including potyviruses, luteoviruses, potato virus Y, barley yellow dwarf-associated viruses and sugar beet virus yellows complexes.

Second, many aphid-borne viruses can be transmitted quickly. Non-persistent transmission can occur during brief probing events. Once that has happened, a later insecticide application may reduce aphid numbers without preventing the infection event. A monitoring system that detects incoming aerial vector pressure before colonisation is therefore more valuable than a system that only measures established colonies.

Third, winged aphid movement is atmospheric. Alate aphids can arrive from outside the field or farm, and their movement is shaped by boundary-layer conditions, temperature, wind, crop phenology and source populations. The key risk signal is not only local abundance on leaves; it is the timing and intensity of aerial arrival.

Fourth, current surveillance is operationally limited. Suction traps, sticky traps, pan traps, crop walking and manual identification remain valuable, but they are sparse, local, labour-intensive and often delayed. AI camera traps improve counting at the trap or plant scale, but they do not observe the vertical air column above the crop. The proposed radar complements these tools by measuring the incoming aerial pathway that current systems largely infer.

Fifth, the need is increasing. Climate change is shifting pest and pathogen distributions, crop protection chemistry is under regulatory and resistance pressure, and growers need stronger evidence before applying insecticides. Earlier and more spatially precise vector warning can support integrated pest management, reduce prophylactic spraying, protect beneficial insects and improve the timing of sampling, diagnostics and intervention.

If successful, Aerial BioScope would change three parts of the measurement landscape.

It would make the lower atmosphere above crops directly observable as a biological domain, allowing disease-vector risk to be detected before symptoms, trap delays or field colonisation dominate the evidence base.

It would link weather, crop health and vector biology in one data stream. A vertically resolved sensor can report when vector-sized insects are flying, at what heights, under which winds and whether activity appears local, transient or part of broader atmospheric movement.

It would create a platform technology for other agricultural and veterinary vector groups. Aphids are the first target, but the same measurement principle could extend to leafhoppers and planthoppers that vector plant pathogens, whiteflies and thrips in protected and field horticulture, and biting midges such as Culicoides where livestock disease surveillance requires earlier aerial-risk intelligence.

### 3. Why this has not yet been done

The necessary scientific and engineering components exist, but they have not been assembled for aphid-scale agricultural vector sensing.

UK vertical-looking radar was a breakthrough for observing insect migration, but the classic systems were largely X-band and tuned to larger high-flying insects. They were not designed for aphid-sized targets or farm-scale disease-vector warning. Operational weather radar and BioDAR/PestDAR-style methods are powerful for broad biological echoes, but their large sample volumes make individual aphid-scale detection and field attribution difficult.

Millimetre-wave radars at Ka and W band are established in cloud physics and are sensitive to small scatterers. However, cloud radars are expensive scientific instruments, usually optimised for hydrometeors and boundary-layer physics rather than crop-vector feature extraction, trap-calibrated biological classification, low-cost deployment and farm decision support.

Modern pest-monitoring stations and AI camera traps observe insects once they enter a trap or settle on plants. They are valuable ground-truthing assets but do not measure incoming flight layers tens to hundreds of metres above the crop. That limitation is important for aphids because damaging virus transmission can be driven by winged migrants that do not need to establish colonies before spreading disease.

The overlooked opportunity is the middle ground: a low-power vertical radar station that borrows the physics of millimetre-wave radar, the autonomy of vertical-looking entomological radar and the deployment model of practical pest stations. The main scientific risk is that aphids are small, radar cross-sections will be weak, rain and clutter can dominate, and radar alone will not provide species-level identification. The project is therefore structured around ground truth, controlled calibration, dual-band discrimination and uncertainty-aware inference rather than unsupported claims of direct species recognition.

### 4. Delivery plan

The proposed work is a 24-month seed project with four work packages.

#### WP1 - System design and bench prototype, months 0-6

- Select and integrate a 94 GHz FMCW W-band radar head and a 35 GHz FMCW Ka-band radar head with colocated vertical boresight.
- Specify beamwidth, chirp bandwidth, dwell pattern, range gates, calibration targets, timing, edge compute, enclosure, radome and weather station.
- Target first-height coverage of 2-300 m, with high-resolution W-band range-Doppler products and Ka-band confirmation/weather context.
- Implement initial processing: range-Doppler maps, clutter removal, target detection, signal-to-noise metrics, dual-band ratios and quality flags.

#### WP2 - Controlled biological calibration, months 4-10

- Measure radar returns from known small insects and non-biological confounders under controlled short-range conditions.
- Focus first on winged aphids and aphid-sized calibration targets, then include larger flies/moths, rain/drizzle simulations where possible, dust/seed particles and beneficial insects.
- Extract W-band amplitude, Ka-band amplitude, W/Ka ratio, polarisation features where hardware allows, Doppler velocity and wingbeat/micro-Doppler signatures.
- Produce a detection envelope: minimum useful target size, range, velocity and weather conditions.

#### WP3 - Field deployment and ground truth, months 8-20

- Deploy one prototype at a crop-edge site and one at a field-centre or comparison site, prioritising cereals, sugar beet, potato or brassica systems with known aphid-virus risk.
- Pair radar with suction or sticky traps, yellow pan traps, camera/IR insect counters, crop phenology notes and local weather.
- Compare radar-derived vector-sized aerial activity with trap catches, species IDs and, where feasible, viral assays or plant disease observations.
- Build an annotated dataset with uncertainty labels: probable aphid-sized target, small insect unknown, larger insect, rain/clutter and non-biological target.

#### WP4 - Classifier, data product and scaling design, months 12-24

- Train interpretable baseline classifiers before any deep-learning model: logistic and gradient-boosted models using radar physics features plus weather and crop context.
- Generate a nightly aphid/vector influx index with height distribution, timing, quality flags and confidence.
- Package outputs in open, reusable formats aligned with existing Avocet radar data practice: metadata-rich files, STAC-style catalogues, validation manifests and browser-ready visualisations.
- Produce a follow-on plan for a small UK network linked to crop disease forecasting, Rothamsted-style aphid monitoring, weather radar biological products and farm decision support.

#### Success criteria

- controlled detection of aphid-sized airborne targets under defined ranges and weather conditions;
- field radar activity explaining meaningful variance in same-night or next-day trap catches;
- demonstrated separation of small-insect activity from rain and larger targets using W/Ka and Doppler features;
- a reproducible dataset and processing chain strong enough to justify a larger network and a disease-vector forecasting programme;
- at least two credible routes to market tested with growers, agronomy providers, crop protection organisations, insurers or public surveillance bodies.

### 5. Applicant and team capability

The applicant brings relevant prior work at the intersection of radar data engineering, biological radar applications and operational environmental data systems.

Through UK WSR Visualizer and the Avocet radar pipeline, the applicant has built a UK-radar-specific software stack around Met Office/NIMROD radar aggregates: catalogue scanning, browser previews, tile generation, animations, geospatial exports, contour products, FastAPI services, STAC catalogues, object-store publication planning, and freshness checks. In parallel, the Avocet JASMIN pipeline converts UK Met Office single-site raw radar archives into daily ODIM-like HDF5 aggregate files, with coverage checking, repair candidate discovery, Slurm submission scripts, and daily operational updates.

The applicant has also scoped a BirdCast UK-style biological radar system using Avocet UK radar data, JASMIN compute, ERA5/GAMB2LE weather features, vol2bird/bioRad-style biological profile extraction and public web/API products. Separately, radar ground-mapping work has been implemented for beam height, terrain blockage, propagation and vertical-profile detection fraction. These capabilities are directly relevant to making biological radar observations interpretable rather than merely detectable.

This prior work provides an end-to-end base for the proposed seed: radar data structures, geospatial calibration, public data infrastructure, validation discipline, biological radar modelling and product-oriented data delivery. The missing capabilities are precisely the ones the seed is designed to add: millimetre-wave RF hardware integration, aphid/vector biology, field validation and commercial translation.

The proposed team should therefore combine:

- a millimetre-wave radar hardware engineer or supplier with W-band and Ka-band FMCW experience;
- an aphid, plant-virus or Rothamsted-style monitoring partner for trap design, identification and vector interpretation;
- a crop disease or agronomy partner for field access, validation and user requirements;
- the applicant's existing Avocet software and radar-data infrastructure for processing, quality control, publication and product development.

The project is not a generic pest-monitoring product. It addresses a specific technical gap: agriculture has extensive atmospheric radar infrastructure and extensive pest monitoring practice, but it still lacks a direct operational measurement of the small airborne biological flux that can determine whether crop disease-vector risk arrives tomorrow.

## Part 2: Commercialisation and Translation

### Why this can become commercially valuable

The commercial proposition is decision advantage. Growers, agronomists, crop processors and crop-protection organisations do not need another isolated sensor unless it changes action. Aerial BioScope is designed to convert an invisible risk signal - incoming vector-sized aerial activity - into earlier and better-timed decisions.

The initial value pools are:

- high-value crops and seed systems where aphid-transmitted viruses create disproportionate losses or quality downgrades, including seed potatoes, sugar beet, cereals, brassicas and protected horticulture;
- agronomy services that need defensible evidence for spray timing, scouting intensity and treatment avoidance;
- producer groups and processors that require regional disease-risk intelligence across multiple farms;
- crop insurers and reinsurers that need objective, weather-linked pest and disease exposure data;
- public surveillance agencies and research networks seeking improved biosphere-atmosphere observations.

The first commercial product should not be positioned as a stand-alone "aphid species radar". The stronger proposition is an integrated vector-risk service: hardware plus data processing plus a validated influx index plus alerts and API access. This framing reduces the biological overclaim risk and makes the system easier to integrate into existing agronomy workflows.

### Product model

The likely commercial model has three layers.

- Hardware station: sale or lease of a rugged W-band/Ka-band vertical radar station with weather sensing, telemetry, edge compute and field maintenance.
- Data service: subscription access to aphid/vector influx indices, quality flags, dashboards, downloadable data and alerts.
- Network intelligence: regional risk layers, model licensing and API integration for agronomy platforms, disease forecast providers, crop processors and insurers.

The seed project will test whether the highest-value entry point is single-farm decision support, crop-cluster monitoring through producer groups, or regional surveillance delivered to agronomy and public-sector partners. The technical design keeps these routes open by separating the sensor, processing pipeline, validated dataset and risk-index product.

### Defensible assets

The commercially defensible assets are expected to be:

- the dual-band calibration dataset linking W-band/Ka-band signatures to aphid-sized targets, confounders, traps and weather;
- the radar feature pipeline and quality-control methods for small biological targets in agricultural boundary-layer conditions;
- the aphid/vector influx index and its validation against trap and crop disease observations;
- deployment know-how for low-power, farm-ready millimetre-wave vertical radar stations;
- integration pathways into crop disease models, agronomy dashboards and regional surveillance networks.

### Route to scale

The seed-stage route to scale is deliberately practical.

- Stage 1: validate detection and field correlation at one or two UK crop sites.
- Stage 2: deploy a small network in one high-value crop system with agronomy and plant-pathology partners.
- Stage 3: integrate vector-risk indices into disease forecasting and decision-support platforms.
- Stage 4: expand from aphids into other vector groups where the same radar architecture and validation model can be reused.

This route supports ARIA's appetite for ambitious measurement technology while keeping a clear line to adoption: growers and agronomists can pay for earlier warning only if the system improves treatment timing, reduces unnecessary spraying, avoids missed outbreaks or supports higher-confidence surveillance.

## Part 3: Timeline, Budget and Administrative Draft

### Timeframe

24 months.

### Requested Budget

Requested amount: GBP 495,000 inclusive of VAT and all direct/indirect costs, to be adjusted to the host organisation's costing model.

Indicative budget:

| Cost area | GBP |
| --- | ---: |
| Applicant time, data engineering and project leadership | 95,000 |
| Radar/data scientist or research engineer | 105,000 |
| Millimetre-wave engineering subcontract or consultancy | 70,000 |
| Entomology/plant pathology field partner and trap/species validation | 55,000 |
| W-band and Ka-band radar modules, antennas, timing, calibration targets | 85,000 |
| Enclosures, radomes, edge compute, power, weather sensors, field deployment | 35,000 |
| Data hosting, JASMIN/cloud, consumables, lab/field assays | 25,000 |
| Travel, field logistics, dissemination and contingency | 25,000 |
| Total | 495,000 |

Alternative smaller scenario: GBP 250,000 over 12 months would deliver a single-site W-band-led proof of concept with Ka-band borrowed, simplified or deferred. The stronger ARIA-shaped bet is the full dual-band 24-month version because dual-band discrimination is central to the hypothesis and because commercialisation depends on trustworthy confounder rejection.

### Background IP

The project can build on pre-existing know-how and code from the Avocet Radar Toolkit and Avocet UK radar pipeline. The new millimetre-wave hardware integration, aphid/vector feature datasets, classifiers, decision indices and farm-deployment design should be treated as new project foreground IP. Commercial radar module firmware or supplier SDKs would be used under standard terms and isolated from the open data-processing layer where necessary.

### Subcontractors

Likely subcontracted work:

- W-band/Ka-band radar hardware design or module integration;
- entomological ground-truthing, aphid identification and crop-virus/vector interpretation;
- field site access and trap servicing if not provided by the host institution;
- limited user-discovery and commercial validation with agronomy, grower and surveillance partners.

### Operating Location and UK Benefit

The project should be run from the UK or with a UK field-validation component. The immediate UK benefit is a new measurement capability for climate-sensitive agricultural pest and disease-vector risk, linked to existing UK strengths in radar, Rothamsted-style insect monitoring, NCAS/JASMIN infrastructure, crop protection science, precision agriculture and public-good environmental sensing.

## Suggested One-Paragraph Summary

Aerial BioScope will build and validate a compact W-band/Ka-band vertical radar station that measures aphid-sized airborne insect flux above crops. It targets a blind spot in Earth-system and agricultural sensing: the moving biological layer that connects weather, climate, crop disease and pest pressure. The project will combine UK vertical-looking radar principles, Australian radar-entomology field practice and compact pest-station deployment patterns to create a trap-calibrated aphid/vector influx index. If successful, it will create a commercialisable agricultural biosphere observatory for earlier disease-vector warning, better targeted crop protection, reduced unnecessary spraying and richer biosphere-atmosphere models.

## Notes Before Submission

- Confirm the formal applicant name, host organisation, named partners and budget treatment before submission.
- Add named partners only when confirmed.
- If Wuxi-specific supplier documentation is available, include it as an engineering deployment precedent. No open peer-reviewed Wuxi dual-band aphid-radar source was verified during drafting.
- Check current ARIA portal status before submission. The original PDF call was dated 23 May 2024 and listed a June 2024 deadline, while the current opportunity page describes Scoping Our Planet opportunity seeds as part of a rolling seed-call experiment.

## Evidence Base and References

ARIA fit:

1. ARIA. "Scoping Our Planet" opportunity space. The page frames the space around closing Earth-system measurement and modelling gaps using frontier platforms, sensors and AI models. https://aria.org.uk/opportunity-spaces/scoping-our-planet/
2. ARIA. "Opportunity seeds: Scoping Our Planet. Call for proposals." v1.0, 23 May 2024. The call states budgets of GBP 10k-500k, maximum project length of three years, and the five core questions used above. https://aria.org.uk/media/hs1j0lj0/aria-opportunity-seeds-scoping-our-planet-call-for-proposals.pdf

Radar entomology and biological flux:

3. Chapman, J.W., Reynolds, D.R. and Smith, A.D. (2003). "Vertical-Looking Radar: A New Tool for Monitoring High-Altitude Insect Migration." BioScience 53(5), 503-511. https://doi.org/10.1641/0006-3568(2003)053[0503:VRANTF]2.0.CO;2
4. Chapman, J.W., Smith, A.D., Woiwod, I.P., Reynolds, D.R. and Riley, J.R. (2002). "Development of vertical-looking radar technology for monitoring insect migration." Computers and Electronics in Agriculture 35, 95-110. https://doi.org/10.1016/S0168-1699(02)00014-5
5. Drake, V.A. and Reynolds, D.R. (2012). Radar Entomology: Observing Insect Flight and Migration. CABI. https://www.cabi.org/bookshop/book/9781845935566/
6. Hu, G., Lim, K.S., Horvitz, N., Clark, S.J., Reynolds, D.R., Sapir, N. and Chapman, J.W. (2016). "Mass seasonal bioflows of high-flying insect migrants." Science 354, 1584-1587. https://doi.org/10.1126/science.aah4379
7. Chapman, J.W., Reynolds, D.R. and Wilson, K. (2015). "Long-range seasonal migration in insects: mechanisms, evolutionary drivers and ecological consequences." Ecology Letters 18, 287-302. https://doi.org/10.1111/ele.12407
8. Wotton, K.R., Gao, B., Menz, M.H.M., Morris, R.K.A., Ball, S.G., Lim, K.S., Reynolds, D.R., Hu, G. and Chapman, J.W. (2019). "Mass Seasonal Migrations of Hoverflies Provide Extensive Pollination and Crop Protection Services." Current Biology 29, 2167-2173.e5. https://doi.org/10.1016/j.cub.2019.05.036
9. Drake, V.A., Chapman, J.W., Lim, K.S., Reynolds, D.R., Riley, J.R. and Smith, A.D. (2017). "Ventral-aspect radar cross sections and polarization patterns of insects at X band and their relation to size and form." International Journal of Remote Sensing 38, 5022-5044.

Millimetre-wave and polarimetric radar precedent:

10. Moran, K.P., Martner, B.E., Post, M.J., Kropfli, R.A., Welsh, D.C. and Widener, K.B. (1998). "An unattended cloud-profiling radar for use in climate research." Bulletin of the American Meteorological Society 79, 443-455. https://doi.org/10.1175/1520-0477(1998)079%3C0443:AUCPRF%3E2.0.CO;2
11. Martner, B.E. and Moran, K.P. (2001). "Using cloud radar polarization measurements to evaluate stratus cloud and insect echoes." Journal of Geophysical Research: Atmospheres 106(D5), 4891-4907.
12. Matrosov, S.Y. (1991). "Theoretical study of radar polarization parameters obtained from cirrus clouds." Journal of the Atmospheric Sciences 48, 1062-1070.

Aphids, plant viruses and agricultural vector relevance:

13. Ng, J.C.K. and Perry, K.L. (2004). "Transmission of plant viruses by aphid vectors." Molecular Plant Pathology 5(5), 505-511. https://doi.org/10.1111/j.1364-3703.2004.00240.x
14. Gadhave, K.R., Gautam, S., Rasmussen, D.A. and Srinivasan, R. (2020). "Aphid Transmission of Potyvirus: The Largest Plant-Infecting RNA Virus Genus." Viruses 12(7), 773. https://doi.org/10.3390/v12070773
15. Gray, S. and Gildow, F.E. (2003). "Luteovirus-aphid interactions." Annual Review of Phytopathology 41, 539-566. https://doi.org/10.1146/annurev.phyto.41.012203.105815
16. Nault, L.R. (1997). "Arthropod transmission of plant viruses: a new synthesis." Annals of the Entomological Society of America 90(5), 521-541. https://doi.org/10.1093/aesa/90.5.521
17. Radcliffe, E.B. and Ragsdale, D.W. (2002). "Aphid-transmitted potato viruses: The importance of understanding vector biology." American Journal of Potato Research 79, 353-386.
18. Ragsdale, D.W., McCornack, B.P., Venette, R.C., Potter, B.D., MacRae, I.V., Hodgson, E.W., O'Neal, M.E., Johnson, K.D., O'Neil, R.J., DiFonzo, C.D., Hunt, T.E., Glogoza, P.A. and Cullen, E.M. (2007). "Economic threshold for soybean aphid (Hemiptera: Aphididae)." Journal of Economic Entomology 100(4), 1258-1267.
19. Hardie, J. and Powell, G. (2002). "Video analysis of aphid flight behaviour." Computers and Electronics in Agriculture 35, 229-242.

Climate, pests and monitoring gap:

20. Bebber, D.P., Ramotowski, M.A.T. and Gurr, S.J. (2013). "Crop pests and pathogens move polewards in a warming world." Nature Climate Change 3, 985-988. https://doi.org/10.1038/nclimate1990
21. Skendzic, S., Zovko, M., Zivkovic, I.P., Lesic, V. and Lemic, D. (2021). "The Impact of Climate Change on Agricultural Insect Pests." Insects 12(5), 440. https://doi.org/10.3390/insects12050440
22. Rydhmer, K. et al. (2021). "Automating insect monitoring using unsupervised near-infrared sensors." arXiv:2108.05435. https://arxiv.org/abs/2108.05435
23. Gao, X., Xue, W., Lennox, C., Stevens, M. and Gao, J. (2023). "Advancing Early Detection of Virus Yellows: Developing a Hybrid Convolutional Neural Network for Automatic Aphid Counting in Sugar Beet Fields." arXiv:2308.05257. https://arxiv.org/abs/2308.05257

Local Avocet work to cite or link if appropriate:

24. UK WSR Visualizer README in this workspace: UK radar app and CLI for aggregate HDF5 files, including catalog scanning, previews, geospatial exports, object-store publication, and STAC.
25. Avocet BirdCast UK implementation plan in this workspace: a proposed UK migration monitoring and forecasting system using Avocet UK Met Office Nimrod radar pipeline, ERA5/GAMB2LE assets, JASMIN and biological-radar tooling.
26. Avocet UK radar ground-mapping practical in this workspace: Python implementation of radar base grids, beam height, terrain blockage, propagation and vertical-profile detection fraction for biological radar products.
