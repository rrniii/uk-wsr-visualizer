from pathlib import Path

from uk_wsr_visualizer.catalog import build_raw_volume_catalog


RAW_VOLUME_BASE = Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site")
OUTPUT = Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/raw-volume-catalog/chenies-2018/catalog.json")
OBJECT_STORE_BASE = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public"


def main() -> None:
    items = build_raw_volume_catalog(
        raw_volume_base=RAW_VOLUME_BASE,
        output=OUTPUT,
        radar="chenies",
        year="2018",
        object_store_base=OBJECT_STORE_BASE,
        metadata_mode="fast",
    )
    print(
        {
            "output": str(OUTPUT),
            "items": len(items),
            "volumes": sum(len(item.raw_volumes) for item in items),
            "records": sum(len(item.quantity_records) for item in items),
        }
    )


if __name__ == "__main__":
    main()
