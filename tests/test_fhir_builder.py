from config_loader import load_scenario
from generate.synthetic_source import generate_source_truth
from transform.expected_exchange import build_expected_exchange
from transform.fhir_builder import build_bundles


def test_build_bundles_removes_stale_exchange_files(tmp_path):
    stale_bundle = tmp_path / "STALE-PATIENT-exchange.json"
    stale_bundle.write_text(
        '{"resourceType": "Bundle", "type": "collection"}',
        encoding="utf-8",
    )

    scenario = load_scenario("A")
    source_truth, patients = generate_source_truth(scenario)
    expected = build_expected_exchange(
        source_truth,
        patients,
    )

    written = build_bundles(
        expected,
        patients,
        tmp_path,
    )

    assert not stale_bundle.exists()
    assert written
    assert all(path.exists() for path in written)