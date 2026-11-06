"""Regression examples for observed ODIM flags and PPC stage meanings."""

import h5py
import numpy as np
import pytest

from uk_wsr_ops.core import physical
from uk_wsr_ops.policies import decide, diagnostic
from uk_wsr_ops.scoring import score


def field(sweep, name, data, *, nodata=255, undetect=0, gain=1, offset=0, task=None):
    g = sweep.create_group(f"data{len(sweep) + 1}")
    g.create_group("what").attrs.update(
        quantity=name, nodata=nodata, undetect=undetect, gain=gain, offset=offset
    )
    g.create_dataset("data", data=np.asarray(data))
    if task:
        g.create_group("how").attrs["task"] = task
    return g


@pytest.fixture
def sweep(tmp_path):
    with h5py.File(tmp_path / "observed-encoding.h5", "w") as h:
        s = h.create_group("dataset1")
        s.create_group("where").attrs["elangle"] = 0.5
        # Two rays cannot form a complete three-gate range neighbourhood here,
        # so no smoothness protection obscures the detector convention.
        field(s, "DBZH", [[20.0, 25.0], [30.0, 35.0]], nodata=-999, undetect=-998)
        yield s


def test_moment_undetect_stays_missing_but_flag_false_is_supported(sweep):
    g = field(sweep, "SEA_CLUTTER_FLAG_LROSE_V2", [[0, 1], [255, 0]])
    assert np.isnan(physical(g)[0, 0])
    got = diagnostic(g)
    np.testing.assert_equal(got, [[0, 1], [np.nan, 0]])


def test_nodata_wins_if_diagnostic_reserved_codes_collide(sweep):
    g = field(sweep, "SEA_CLUTTER_FLAG_LROSE_V2", [[0, 1]], nodata=0)
    assert np.isnan(diagnostic(g)[0, 0])


def test_invalid_binary_flag_fails_instead_of_becoming_evidence(sweep):
    g = field(sweep, "SEA_CLUTTER_FLAG_LROSE_V2", [[0, 2]])
    with pytest.raises(ValueError, match="binary diagnostic"):
        diagnostic(g)


def test_lrose_negative_flags_provide_coverage(sweep):
    field(sweep, "PERSISTENT_CLUTTER_FLAG_LROSE_V2", [[0, 0], [0, 0]])
    field(sweep, "GROUND_CLUTTER_PID_FLAG_LROSE_V2", [[0, 1], [255, 0]])
    d = decide(sweep, "lrose")
    assert d["supported"].sum() == 3
    assert not d["remove"].any()
    assert d["uncertain"][0, 1]


def baltrad(sweep, quality, residual):
    field(sweep, "QIND_BALTRAD_V1", quality, nodata=-999, undetect=-998)
    field(
        sweep,
        "CLUTTER_PROB_BALTRAD_V1",
        1 - np.asarray(quality),
        nodata=-999,
        undetect=-998,
    )
    return field(
        sweep, "RESIDUAL_CLUTTER_MASK_BALTRAD_V1", residual, nodata=-999, undetect=-998
    )


def test_baltrad_retention_one_is_not_a_clutter_vote(sweep):
    baltrad(sweep, [[1, 1], [1, 1]], [[1, 0], [-1, 1]])
    d = decide(sweep, "baltrad")
    assert d["supported"].all()
    assert not d["remove"].any()
    assert d["uncertain"].sum() == 1
    assert d["uncertain"][0, 1]
    assert d["detectors"]["residual_nonretained"]["supported"].sum() == 3


def test_baltrad_native_fuzzy_stage_does_not_require_residual_agreement(sweep):
    baltrad(sweep, [[0.1, 0.1], [0.75, 1]], [[0, 1], [0, 1]])
    d = decide(sweep, "baltrad")
    np.testing.assert_equal(d["remove"], [[True, True], [False, False]])
    assert d["uncertain"][1, 0]  # threshold equality passes the fuzzy stage


def test_baltrad_preprocessed_weak_values_cannot_become_clutter_evidence(sweep):
    field(sweep, "TH", [[-32, -20], [20, 20]], nodata=-999, undetect=-998)
    baltrad(sweep, [[0.1, 0.1], [1, 1]], [[0, 0], [1, 1]])
    d = decide(sweep, "baltrad")
    assert not d["supported"][0, 0] and not d["remove"][0, 0]
    assert d["remove"][0, 1]


def test_baltrad_protects_coherent_weather_evidence(sweep):
    baltrad(sweep, [[0.1, 0.1], [0.1, 0.1]], [[0, 0], [0, 0]])
    field(sweep, "RHOHV", [[0.98, 0.5], [0.5, 0.5]], nodata=-999, undetect=-998)
    d = decide(sweep, "baltrad")
    assert not d["remove"][0, 0] and d["uncertain"][0, 0]
    assert d["remove"].sum() == 3


def test_baltrad_complement_mismatch_fails(sweep):
    baltrad(sweep, [[0.1, 0.1], [0.1, 0.1]], [[0, 0], [0, 0]])
    for g in sweep.values():
        if (
            isinstance(g, h5py.Group)
            and "what" in g
            and g["what"].attrs["quantity"] == "QIND_BALTRAD_V1"
        ):
            g["data"][...] = 0.9
    with pytest.raises(ValueError, match="complement"):
        decide(sweep, "baltrad")


def rack_field(sweep, name, data):
    return field(
        sweep,
        name,
        data,
        gain=0.004,
        offset=-0.004,
        task="fi.fmi.Rack.AnDRe." + name + "Op",
    )


def test_rack_reserved_no_detection_overrides_encoding_offset(sweep):
    g = rack_field(sweep, "Emitter", [[0, 1], [251, 255]])
    np.testing.assert_allclose(diagnostic(g), [[0, 0], [1, np.nan]], equal_nan=True)


def test_rack_single_detector_is_visible_without_invented_union(sweep):
    rack_field(sweep, "Emitter", [[251, 0], [0, 255]])
    rack_field(sweep, "Jamming", [[0, 0], [0, 0]])
    d = decide(sweep, "rack")
    assert d["supported"].sum() == 3
    assert not d["remove"].any()
    assert d["uncertain"][0, 0]
    assert d["detectors"]["EmitterOp"]["positive"].sum() == 1


def test_rack_out_of_scope_is_not_a_negative_detection(sweep):
    rack_field(sweep, "Emitter", np.zeros((2, 2)))
    rack_field(sweep, "Jamming", np.zeros((2, 2)))
    sweep["where"].attrs["elangle"] = 89.9
    assert not decide(sweep, "rack")["supported"].any()


def test_wrong_diagnostic_geometry_fails(sweep):
    field(sweep, "PERSISTENT_CLUTTER_FLAG_LROSE_V2", [[0]])
    field(sweep, "GROUND_CLUTTER_PID_FLAG_LROSE_V2", np.zeros((2, 2)))
    with pytest.raises(ValueError, match="geometry"):
        decide(sweep, "lrose")


def test_whole_scope_scores_expose_unsupported_retained_artefacts():
    yes = np.ones((2, 2), bool)
    d = {
        "valid": yes,
        "supported": np.array([[1, 0], [0, 0]], bool),
        "remove": np.array([[1, 0], [0, 0]], bool),
        "uncertain": ~yes,
    }
    region = {
        "vertices": [[0, 0], [0, 2], [2, 2], [2, 0]],
        "label": "interference",
        "action": "remove",
    }
    s = score(d, [region])
    assert s["artefact_removal"] == 1
    assert s["whole_scope"]["artefact_removal"] == 0.25
    assert s["whole_scope"]["unsupported_artefact_gates"] == 3
    assert s["whole_scope_labelled_gates"] == 4
