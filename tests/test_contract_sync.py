"""Keep the two halves of the Validation Contract in agreement.

The contract exists in two places by design: `config/v1_elements.yaml` is what
the engine reads, and `docs/data_dictionary/v1_validation_contract.md` is what a
reviewer reads. Two representations of the same thing drift, and the drift is
silent -- the code keeps working while the documentation quietly becomes wrong.

Documentation that has quietly become wrong is worse than none, because it is
still trusted. These tests make drift fail the build.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "v1_elements.yaml"
DOC = ROOT / "docs" / "data_dictionary" / "v1_validation_contract.md"

ELEMENTS = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
DOC_TEXT = DOC.read_text(encoding="utf-8")


@pytest.mark.parametrize("element", [e["element_name"] for e in ELEMENTS["elements"]])
def test_every_declared_element_is_documented(element):
    assert f"`{element}`" in DOC_TEXT, (
        f"Element '{element}' is declared in config/v1_elements.yaml but does "
        "not appear in the data dictionary. Add it, or a reviewer will be "
        "reading a contract that no longer describes the system."
    )


@pytest.mark.parametrize("verdict", list(ELEMENTS["failure_classes"]))
def test_every_failure_class_is_documented(verdict):
    assert f"`{verdict}`" in DOC_TEXT, (
        f"Failure class '{verdict}' is not documented in the data dictionary."
    )


@pytest.mark.parametrize("verdict", list(ELEMENTS["pass_classes"]))
def test_every_pass_class_is_documented(verdict):
    assert f"`{verdict}`" in DOC_TEXT


def test_contract_version_matches_the_document():
    version = str(ELEMENTS["contract_version"])
    assert re.search(rf"\*\*Contract version:\*\*\s*{re.escape(version)}", DOC_TEXT), (
        f"config declares contract_version {version}, which the data "
        "dictionary header does not state."
    )


def test_every_element_declares_a_tolerance_field():
    """Explicit `tolerance: null` is required; a missing key is not the same.

    An unstated tolerance is the most common way a data-quality metric becomes
    irreproducible -- the reader cannot tell whether zero was chosen or simply
    never considered.
    """
    for element in ELEMENTS["elements"]:
        assert "tolerance" in element, (
            f"{element['element_name']} does not declare a tolerance. Use "
            "'tolerance: null' if it does not apply."
        )


def test_every_element_declares_a_fhir_path():
    """Traceability from source through FHIR to destination must be documented."""
    for element in ELEMENTS["elements"]:
        assert element.get("fhir_path"), (
            f"{element['element_name']} has no fhir_path, so a reviewer cannot "
            "trace where it lives in the exchange representation."
        )


def test_normalizers_and_comparators_all_exist():
    """Catch a contract typo at test time rather than mid-run."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from validate.normalize import NORMALIZERS
    from validate.rules import COMPARATORS

    for element in ELEMENTS["elements"]:
        assert element["normalization"] in NORMALIZERS, (
            f"{element['element_name']} names normalizer "
            f"'{element['normalization']}', which is not implemented."
        )
        assert element["comparison"] in COMPARATORS, (
            f"{element['element_name']} names comparator "
            f"'{element['comparison']}', which is not implemented."
        )
