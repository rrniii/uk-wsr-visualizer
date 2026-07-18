from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from uk_wsr_visualizer.qc_evidence import EvidenceFlag, NuisanceFlag
from uk_wsr_visualizer.receiver_noise_audit import (
    audit_receiver_noise_physics,
    write_receiver_noise_physics_audit,
)


def test_receiver_noise_audit_attributes_physical_support(
    tmp_path: Path,
) -> None:
    shape = (360, 189)
    ranges = (np.arange(shape[1]) + 0.5) * 0.6
    values = np.broadcast_to(
        20.0 * np.log10(ranges) - 27.3,
        shape,
    ).astype("float32")
    evidence = np.full(
        shape,
        int(EvidenceFlag.HIGH_CI) | int(EvidenceFlag.LOW_SQI),
        dtype="uint32",
    )
    nuisance = np.full(
        shape,
        int(NuisanceFlag.RECEIVER_NOISE),
        dtype="uint16",
    )
    artifact = tmp_path / "artifact.npz"
    np.savez_compressed(
        artifact,
        dbzh_raw=values,
        baseline_evidence_mask=evidence,
        baseline_nuisance_mask=nuisance,
    )
    results = tmp_path / "validation_results.json"
    results.write_text(
        json.dumps(
            {
                "schema": "uk_wsr_background_validation_results",
                "complete": True,
                "configuration_sha256": "a" * 64,
                "records": [
                    {
                        "artifact_npz": str(artifact),
                        "job_id": "job",
                        "target_id": "target",
                        "radar": "chenies",
                        "pulse": "sp",
                        "elevation_deg": 9.0,
                        "geometry_class": "ppi",
                        "rstart_km": 0.0,
                        "rscale_m": 600.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    audit = audit_receiver_noise_physics(results)

    assert audit["record_count"] == 1
    row = audit["records"][0]
    assert row["fit_qualified"] is True
    assert row["physically_supported_receiver_noise_fraction"] > 0.70
    assert audit["groups"]["sp_9_degree"]["qualified_sweep_count"] == 1

    output_json, output_csv = write_receiver_noise_physics_audit(
        audit,
        output_json=tmp_path / "audit.json",
        output_csv=tmp_path / "audit.csv",
    )
    assert output_json.is_file()
    assert output_csv is not None and output_csv.is_file()
