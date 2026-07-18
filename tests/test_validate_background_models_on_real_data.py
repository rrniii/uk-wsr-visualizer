import importlib.util
from pathlib import Path
from types import SimpleNamespace


_MODULE_PATH = Path(__file__).parents[1] / "tools" / "validate_background_models_on_real_data.py"
_SPEC = importlib.util.spec_from_file_location("validate_background_models_on_real_data", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_stratified_jobs = _MODULE._stratified_jobs


def _job(radar: str, target_id: str, date: str, time: str):
    return SimpleNamespace(
        target=SimpleNamespace(radar=radar, target_id=target_id),
        sweep=SimpleNamespace(date=date, time=time),
    )


def test_stratified_jobs_rotates_across_radars_before_repeating() -> None:
    jobs = [
        _job("alpha", "alpha-a", "20250101", "1200"),
        _job("alpha", "alpha-b", "20250401", "0000"),
        _job("bravo", "bravo-a", "20250701", "1200"),
        _job("bravo", "bravo-b", "20251001", "0000"),
        _job("charlie", "charlie-a", "20250101", "1200"),
        _job("charlie", "charlie-b", "20250401", "0000"),
    ]

    selected = _stratified_jobs(jobs, 4)

    assert [job.target.radar for job in selected[:3]] == [
        "alpha",
        "bravo",
        "charlie",
    ]
    assert {job.target.radar for job in selected} == {
        "alpha",
        "bravo",
        "charlie",
    }
    assert len({job.target.target_id for job in selected}) == 4
