from argparse import Namespace
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uk_wsr_visualizer.catalog import CatalogItem, QuantityRecord
from uk_wsr_visualizer.cli import _wct_suite_cases_from_payload
from uk_wsr_visualizer.export import ExportRequest
from uk_wsr_visualizer.wct_parity import (
    WctParityCase,
    compare_outputs,
    evaluate_comparison,
    run_parity_report,
    shell_command,
    wct_command,
    write_wct_batch_config,
)


def item(source: Path) -> CatalogItem:
    return CatalogItem(
        radar="thurnham",
        radar_num="20",
        date="20260614",
        path=str(source),
        file_size=source.stat().st_size,
        modified_time=0,
        pulses=["lp"],
        times=["0000"],
        quantities=["DBZH"],
        quantity_records=[
            QuantityRecord(
                pulse="lp",
                time="0000",
                dataset="1",
                kind="data",
                index="1",
                quantity="DBZH",
            )
        ],
        object_key="uk-radar/source.h5",
    )


class WctParityTests(unittest.TestCase):
    def write_kmz(self, path: Path, north: float = 55.0) -> None:
        kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <GroundOverlay>
      <LatLonBox>
        <north>{north}</north>
        <south>50.0</south>
        <east>2.0</east>
        <west>-6.0</west>
      </LatLonBox>
    </GroundOverlay>
  </Document>
</kml>
"""
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("doc.kml", kml)

    def test_wct_batch_config_and_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.h5"
            source.write_bytes(b"fake")
            case = WctParityCase(
                case_id="case-1",
                item=item(source),
                request=ExportRequest(
                    radar="thurnham",
                    date="20260614",
                    format="geotiff",
                    pulse="lp",
                    time="0000",
                    quantity="DBZH",
                    filters={"max_range_km": 100, "cappi_height_m": 1500},
                ),
            )
            config = root / "wctBatchConfig.xml"
            write_wct_batch_config(case, config)
            text = config.read_text(encoding="utf-8")
            self.assertIn("<variable>Reflectivity</variable>", text)
            self.assertIn("<maxRange>100</maxRange>", text)
            self.assertIn('constantAltitudesInMeters="1500"', text)
            command = wct_command(case, config, root / "out.tif", Path("/Applications/WCT-4.9.1.app"))
            self.assertEqual(command[2], str(root / "out.tif"))
            self.assertEqual(command[3], "geotiff")
            self.assertIn("wct-export.sh", shell_command(command))

    def test_wct_suite_cases_from_payload_expands_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.h5"
            source.write_bytes(b"fake")
            args = Namespace(
                cases_json=None,
                formats="geotiff,kmz",
                radar="thurnham",
                date="20260614",
                pulse="lp",
                time="0000",
                quantity="DBZH",
                dataset=None,
                wct_input_path=None,
                case_id="release",
                min_range_km=None,
                max_range_km=100.0,
                min_azimuth_deg=None,
                max_azimuth_deg=None,
                min_value=None,
                max_value=None,
                cappi_height_m=None,
                palette_stops=None,
            )
            cases = _wct_suite_cases_from_payload(args, [item(source)])
            self.assertEqual([case.request.format for case in cases], ["geotiff", "kmz"])
            self.assertEqual(cases[0].case_id, "release-geotiff")
            self.assertEqual(cases[0].request.filters["max_range_km"], 100.0)

    def test_wct_suite_cases_from_json_expands_formats_and_wct_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.h5"
            source.write_bytes(b"fake")
            cases_json = root / "cases.json"
            cases_json.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "json-case",
                                "radar": "thurnham",
                                "date": "20260614",
                                "pulse": "lp",
                                "time": "0000",
                                "quantity": "DBZH",
                                "formats": ["shapefile", "cf_netcdf"],
                                "wct_input_path": "/reference/volume.h5",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = Namespace(
                cases_json=str(cases_json),
                formats="geotiff",
                radar=None,
                date=None,
                pulse=None,
                time=None,
                quantity=None,
                dataset=None,
                wct_input_path=None,
                case_id=None,
                min_range_km=None,
                max_range_km=None,
                min_azimuth_deg=None,
                max_azimuth_deg=None,
                min_value=None,
                max_value=None,
                cappi_height_m=None,
                palette_stops=None,
            )
            cases = _wct_suite_cases_from_payload(args, [item(source)])
            self.assertEqual([case.request.format for case in cases], ["shapefile", "cf_netcdf"])
            self.assertEqual(cases[1].case_id, "json-case-cf_netcdf")
            self.assertEqual(cases[0].wct_input_path, "/reference/volume.h5")

    def test_wct_suite_cases_rejects_unsupported_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.h5"
            source.write_bytes(b"fake")
            args = Namespace(
                cases_json=None,
                formats="geotiff,png",
                radar="thurnham",
                date="20260614",
                pulse="lp",
                time="0000",
                quantity="DBZH",
                dataset=None,
                wct_input_path=None,
                case_id="bad",
                min_range_km=None,
                max_range_km=None,
                min_azimuth_deg=None,
                max_azimuth_deg=None,
                min_value=None,
                max_value=None,
                cappi_height_m=None,
                palette_stops=None,
            )
            with self.assertRaises(SystemExit):
                _wct_suite_cases_from_payload(args, [item(source)])

    def test_dry_run_report_records_visualizer_output_and_skipped_wct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.h5"
            source.write_bytes(b"fake")
            case = WctParityCase(
                case_id="case-1",
                item=item(source),
                request=ExportRequest(
                    radar="thurnham",
                    date="20260614",
                    format="native_hdf5",
                ),
            )
            report = run_parity_report([case], root / "report", wct_app=Path("/missing/WCT.app"), execute_wct=False)
            self.assertEqual(len(report.results), 1)
            result = report.results[0]
            self.assertEqual(result.visualizer_status, "complete")
            self.assertEqual(result.wct_status, "skipped")
            self.assertTrue(result.visualizer_sha256)
            self.assertEqual(result.parity_status, "not_comparable")
            self.assertIn("not configured", " ".join(result.notes))

    def test_require_comparison_makes_skipped_wct_report_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.h5"
            source.write_bytes(b"fake")
            case = WctParityCase(
                case_id="case-1",
                item=item(source),
                request=ExportRequest(radar="thurnham", date="20260614", format="native_hdf5"),
            )
            report = run_parity_report(
                [case],
                root / "report",
                wct_app=Path("/missing/WCT.app"),
                execute_wct=False,
                require_comparison=True,
            )
            self.assertFalse(report.ok)

    def test_kmz_comparison_records_latlon_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            visualizer = root / "visualizer.kmz"
            wct = root / "wct.kmz"
            self.write_kmz(visualizer)
            self.write_kmz(wct)
            comparison = compare_outputs(visualizer, wct, "kmz")
            self.assertEqual(comparison["driver"], "kmz")
            self.assertTrue(comparison["latlon_box_match"])
            self.assertEqual(evaluate_comparison(comparison), "passed")

    def test_kmz_comparison_fails_on_extent_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            visualizer = root / "visualizer.kmz"
            wct = root / "wct.kmz"
            self.write_kmz(visualizer, north=55.0)
            self.write_kmz(wct, north=55.5)
            comparison = compare_outputs(visualizer, wct, "kmz")
            self.assertFalse(comparison["latlon_box_match"])
            self.assertEqual(evaluate_comparison(comparison), "failed")


if __name__ == "__main__":
    unittest.main()
