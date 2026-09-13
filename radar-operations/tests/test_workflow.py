import h5py
import numpy as np
import pytest
from fastapi.testclient import TestClient

from uk_wsr_ops.core import atomic, digest, fields, manifest, physical, preserved, sha
from uk_wsr_ops.operations import activate, clean_product, approved, validate_cleaned
from uk_wsr_ops.policies import coherent_echo, decide
from uk_wsr_ops.prepare import merge_rack
from uk_wsr_ops.review import create_app
from uk_wsr_ops.scoring import polygon_mask, score


def fixture(path, diagnostic=False):
    with h5py.File(path, "w") as h:
        h.attrs["Conventions"] = "ODIM_H5/V2_2"
        s = h.create_group("dataset1")
        w = s.create_group("where")
        w.attrs.update(elangle=0.5, rstart=0.0, rscale=1000.0, nrays=4, nbins=5)
        data = s.create_group("data1")
        data.create_group("what").attrs.update(
            quantity="DBZH", gain=0.5, offset=-32.0, nodata=255, undetect=0
        )
        data.create_dataset("data", data=np.full((4, 5), 100, dtype="uint8"))
        if diagnostic:
            d = s.create_group("data2")
            d.create_group("what").attrs.update(
                quantity="QC_DECISION_PYRAD_V3", gain=1.0, offset=0.0, nodata=255
            )
            a = np.zeros((4, 5), np.uint8)
            a[0, 0] = 1
            a[1, 1] = 2
            d.create_dataset("data", data=a)


def test_preservation_includes_attributes(tmp_path):
    a, b = tmp_path / "a.h5", tmp_path / "b.h5"
    fixture(a)
    fixture(b, True)
    preserved(a, b)
    with h5py.File(b, "r+") as h:
        h.attrs["Conventions"] = "ODIM_H5/V2_4"
    with pytest.raises(ValueError, match="attribute"):
        preserved(a, b)


def test_cleaning_retains_native_and_ambiguous_echo(tmp_path):
    a, b, c = [tmp_path / n for n in ("a.h5", "b.h5", "clean.h5")]
    fixture(a)
    fixture(b, True)
    clean_product(a, b, c, "pyrad")
    preserved(a, c)
    validate_cleaned(a, b, c, "pyrad")
    with h5py.File(c, "r") as h:
        f = fields(h["dataset1"])
        clean = physical(f["DBZH_CLEAN_OPS"])
        assert np.isnan(clean[0, 0])
        assert clean[1, 1] == 18
        assert np.isnan(clean).sum() == 1
    with pytest.raises(ValueError):
        clean_product(a, b, a, "pyrad")


def test_missing_capability_is_not_clean_retention(tmp_path):
    a = tmp_path / "a.h5"
    fixture(a)
    with h5py.File(a) as h:
        d = decide(h["dataset1"], "lrose")
    result = score(
        d,
        [
            {
                "vertices": [[0, 0], [0, 5], [4, 5], [4, 0]],
                "label": "weather",
                "action": "retain",
            }
        ],
    )
    assert result["supported_gates"] == 0
    assert result["useful_echo_loss"] is None


def test_polygon_conflict_not_scored():
    shape = (4, 5)
    mask = np.ones(shape, bool)
    d = {"valid": mask, "supported": mask, "remove": mask, "uncertain": ~mask}
    all_region = {
        "vertices": [[0, 0], [0, 5], [4, 5], [4, 0]],
        "label": "weather",
        "action": "retain",
    }
    conflict = {**all_region, "label": "clutter", "action": "remove"}
    r = score(d, [all_region, conflict])
    assert r["labelled_gates"] == 0
    assert r["ignored_gates"] == 20
    with pytest.raises(ValueError):
        polygon_mask(shape, [[0, 0], [1, 1], [5, 5]])


def test_scoring_detects_useful_echo_loss():
    yes = np.ones((2, 2), bool)
    removed = np.array([[True, False], [False, False]])
    r = score(
        {"valid": yes, "supported": yes, "remove": removed, "uncertain": ~yes},
        [
            {
                "vertices": [[0, 0], [0, 2], [2, 2], [2, 0]],
                "action": "retain",
                "label": "biology",
            }
        ],
    )
    assert r["useful_echo_loss"] == 0.25
    assert r["removal_precision"] == 0
    assert r["artefact_removal"] is None


def test_coherent_protection_does_not_wrap_range():
    protected = coherent_echo(np.ones((5, 5)))
    assert protected[:, 1:-1].all()
    assert not protected[:, 0].any() and not protected[:, -1].any()


def test_gain_offset_nodata_undetect(tmp_path):
    a = tmp_path / "a.h5"
    fixture(a)
    with h5py.File(a, "r+") as h:
        g = fields(h["dataset1"])["DBZH"]
        g["data"][0, :3] = [0, 255, 100]
        d = physical(g)
        assert np.isnan(d[0, :2]).all()
        assert d[0, 2] == 18


def test_rack_merge_preserves_metadata(tmp_path):
    a, b, c = [tmp_path / n for n in ("a.h5", "rack.h5", "merged.h5")]
    fixture(a)
    fixture(b)
    with h5py.File(b, "r+") as h:
        h.attrs["Conventions"] = "CHANGED"
        q = h["dataset1"].create_group("quality1")
        q.create_group("how").attrs["task"] = "fi.fmi.Rack.AnDRe.JammingOp"
        q.create_group("what").attrs.update(quantity="QIND", gain=1.0, offset=0.0)
        q.create_dataset("data", data=np.ones((4, 5)))
    merge_rack(a, b, c, {"source_sha256": sha(a), "output_sha256": sha(b)})
    preserved(a, c)
    with h5py.File(c) as h:
        assert "quality1" in h["dataset1"]


def test_no_silent_release_without_scientific_decision(tmp_path):
    with pytest.raises(ValueError):
        approved({"status": "pending_review"}, "pyrad")
    atomic(
        tmp_path / "catalogue.json",
        {
            "entries": [{}],
            "source_fallback": False,
            "decision": {"status": "pending_review", "processor": "pyrad"},
        },
    )
    with pytest.raises(ValueError):
        activate(tmp_path, tmp_path / "catalogue.json")
    assert not (tmp_path / "selected.json").exists()


def test_manifest_integrity(tmp_path):
    doc = {
        "schema": "uk_wsr_ops_archive_manifest",
        "cases": [{"case_id": "one", "source_sha256": "0" * 64}],
    }
    doc["manifest_sha256"] = digest(doc)
    atomic(tmp_path / "m.json", doc)
    assert manifest(tmp_path / "m.json")
    doc["cases"][0]["case_id"] = "other"
    atomic(tmp_path / "m.json", doc)
    with pytest.raises(ValueError):
        manifest(tmp_path / "m.json")


def test_review_enforces_reveal_and_retains_label_provenance(tmp_path):
    source = tmp_path / "source.h5"
    fixture(source)
    doc = {
        "schema": "uk_wsr_ops_archive_manifest",
        "cases": [
            {
                "case_id": "one",
                "source_path": str(source),
                "source_sha256": sha(source),
                "radar": "test",
                "pulse": "lp",
            }
        ],
    }
    doc["manifest_sha256"] = digest(doc)
    atomic(tmp_path / "m.json", doc)
    config = {
        "manifest": str(tmp_path / "m.json"),
        "source_root": str(tmp_path),
        "state_root": str(tmp_path / "state"),
        "processors": {
            p: {"output_root": str(tmp_path / p)}
            for p in ("baltrad", "lrose", "pyrad", "rack")
        },
    }
    client = TestClient(create_app(config))
    headers = {"X-Radar-Review": "1"}
    assert client.get("/").status_code == 200
    assert (
        client.get(
            "/api/cases/one/image?sweep=dataset1&candidate=A&reviewer=test"
        ).status_code
        == 403
    )
    label = {
        "reviewer": "test",
        "sweep": "dataset1",
        "label": "weather",
        "vertices": [[0, 0], [0, 2], [2, 2], [2, 0]],
    }
    assert client.post("/api/cases/one/annotations", json=label).status_code == 403
    assert client.post(
        "/api/cases/one/annotations", json=label, headers=headers
    ).json()["source_first"]
    reveal = client.post(
        "/api/cases/one/reveal", json={"reviewer": "test"}, headers=headers
    )
    assert all(c["processor"] is None for c in reveal.json()["candidates"])
    assert not client.post(
        "/api/cases/one/annotations", json=label, headers=headers
    ).json()["source_first"]
    assert len(client.get("/api/export").json()) == 1
    assert len(client.get("/api/export?strict=false").json()) == 2
    assert (
        client.get("/api/cases/one/image?sweep=dataset1&projection=polar").status_code
        == 409
    )
    with h5py.File(source, "r+") as h:
        h["dataset1/data1/data"][0, 0] = 101
    assert client.get("/api/cases/one/image?sweep=dataset1").status_code == 409
    assert (
        client.post(
            "/api/cases/one/annotations", json=label, headers=headers
        ).status_code
        == 409
    )


def test_operational_release_resume_selection_and_tampering(tmp_path):
    from uk_wsr_ops.operations import run_one, publish_catalog, geometry_id, code_digest
    from uk_wsr_ops.policies import POLICIES
    from uk_wsr_ops.batch import selected_product

    native = tmp_path / "native"
    native.mkdir()
    source = native / "one.h5"
    fixture(source)
    products = tmp_path / "pyrad"
    products.mkdir()
    evidence = products / "one.h5"
    fixture(evidence, True)
    case = {
        "case_id": "one",
        "source_path": str(source),
        "source_sha256": sha(source),
        "radar": "test",
        "pulse": "lp",
    }
    atomic(
        str(evidence) + ".pyrad.json",
        {"source_sha256": sha(source), "output_sha256": sha(evidence)},
    )
    annotations = tmp_path / "labels.json"
    atomic(
        annotations,
        [
            {"source_first": True, "action": "retain"},
            {"source_first": True, "action": "remove"},
        ],
    )
    decision = {
        "status": "approved",
        "processor": "pyrad",
        "reviewer": "fixture",
        "rationale": "Synthetic integration test only",
        "blocking_failures": [],
        "coherent_echo_loss_accepted": False,
        "code_sha256": code_digest(),
        "policy_sha256": digest(POLICIES["pyrad"]),
        "supported_groups": ["test|lp|" + geometry_id(source)],
        "review_evidence_path": str(annotations),
        "review_evidence_sha256": sha(annotations),
    }
    dependencies = {str(annotations): sha(annotations)}
    decision["runtime_identity_sha256"] = digest(dependencies)
    config = {
        "source_root": str(native),
        "processors": {
            "pyrad": {"output_root": str(products), "dependency_sha256": dependencies}
        },
    }
    releases = tmp_path / "releases"
    first = run_one(config, releases, case, decision)
    second = run_one(config, releases, case, decision)
    assert first == second
    cat = publish_catalog(
        releases, {"cases": [case], "manifest_sha256": "test"}, decision
    )
    activate(releases, cat)
    assert selected_product(releases, "one")["quantity"] == "DBZH_CLEAN_OPS"
    with pytest.raises(FileNotFoundError):
        selected_product(releases, "missing")
    with h5py.File(first["output_path"], "r+") as h:
        fields(h["dataset1"])["DBZH_CLEAN_OPS"]["data"][1, 1] = 999
    with pytest.raises(ValueError):
        selected_product(releases, "one")
    with pytest.raises(ValueError):
        activate(releases, cat)


def test_pack_keeps_representative_sp_capability_cases(tmp_path):
    from uk_wsr_ops.evaluation import build_pack
    from uk_wsr_ops.policies import POLICIES

    cases = []
    for radar in range(17):
        for pulse in ("lp", "sp"):
            for season in ("winter", "summer"):
                cid = f"r{radar}-{pulse}-{season}"
                case = {
                    "case_id": cid,
                    "radar": f"r{radar}",
                    "pulse": pulse,
                    "season": season,
                }
                cases.append(case)
                metrics = {
                    p: {"supported": 0 if p == "rack" and pulse == "sp" else 10}
                    for p in POLICIES
                }
                row = {
                    **case,
                    "sweep": "dataset1",
                    "candidate_count": 4,
                    "metrics": metrics,
                    "disagreement": radar / 17,
                    "potential_damage_proxy": radar / 34,
                }
                atomic(
                    tmp_path / "metrics" / (cid + ".json"),
                    {
                        "policy_hashes": {p: digest(v) for p, v in POLICIES.items()},
                        "sweeps": [row, {**row, "sweep": "dataset2"}],
                    },
                )
    doc = {"cases": cases, "manifest_sha256": "fixed"}
    pack = build_pack({"state_root": str(tmp_path)}, doc)
    assert pack["complete"] and len(pack["cards"]) == 24
    representative = [r for r in pack["cards"] if r["selection"] == "representative"]
    assert len(representative) == 12
    assert sum(r["pulse"] == "sp" for r in representative) == 6
    assert all(
        r["pulse"] == "lp" for r in pack["cards"] if r["selection"] != "representative"
    )
    assert len({(r["case_id"], r["sweep"]) for r in pack["cards"]}) == 24
    assert len({r["case_id"] for r in pack["cards"]}) == 24
