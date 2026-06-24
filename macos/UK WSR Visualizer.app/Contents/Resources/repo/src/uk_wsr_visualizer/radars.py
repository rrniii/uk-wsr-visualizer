"""UK radar site metadata used by the UK WSR aggregate pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RadarSite:
    slug: str
    radar_num: str
    label: str
    latitude: float | None = None
    longitude: float | None = None


RADARS: tuple[RadarSite, ...] = (
    RadarSite("castor-bay", "07", "Castor Bay"),
    RadarSite("chenies", "05", "Chenies"),
    RadarSite("clee-hill", "03", "Clee Hill"),
    RadarSite("cobbacombe", "16", "Cobbacombe"),
    RadarSite("crug-y-gorrllwyn", "10", "Crug-y-Gorrllwyn"),
    RadarSite("deanhill", "21", "Dean Hill"),
    RadarSite("druima-starraig", "15", "Druima Starraig"),
    RadarSite("dudwick", "14", "Dudwick"),
    RadarSite("hameldon-hill", "04", "Hameldon Hill"),
    RadarSite("high-moorsley", "23", "High Moorsley"),
    RadarSite("holehead", "18", "Holehead"),
    RadarSite("ingham", "09", "Ingham"),
    RadarSite("jersey", "12", "Jersey"),
    RadarSite("munduff-hill", "19", "Munduff Hill"),
    RadarSite("predannack", "08", "Predannack"),
    RadarSite("thurnham", "20", "Thurnham"),
    RadarSite("wardon-hill", "11", "Wardon Hill"),
)

RADAR_BY_SLUG = {radar.slug: radar for radar in RADARS}
RADAR_NUM_BY_SLUG = {radar.slug: radar.radar_num for radar in RADARS}


def radar_records() -> list[dict[str, object]]:
    return [asdict(radar) for radar in RADARS]


def require_radar(slug: str) -> RadarSite:
    try:
        return RADAR_BY_SLUG[slug]
    except KeyError as exc:
        raise ValueError(f"unknown radar: {slug}") from exc

