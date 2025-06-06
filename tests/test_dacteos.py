import pytest
from brazilfiscalreport.dacte.dacteos import DacteOS
from tests.conftest import assert_pdf_equal, get_pdf_output_path


@pytest.fixture
def load_cte_os_xml(load_xml):
    def _load_cte_os_xml(filename):
        return load_xml(filename)
    return _load_cte_os_xml


def test_dacteos_default(tmp_path, load_cte_os_xml):
    cteos_xml_content = load_cte_os_xml("cteos_test_1.xml")

    dacteos_instance = DacteOS(xml_content=cteos_xml_content)

    pdf_path = get_pdf_output_path("dacteos", "dacteos_default")

    assert_pdf_equal(dacteos_instance, pdf_path, tmp_path, generate=True)
