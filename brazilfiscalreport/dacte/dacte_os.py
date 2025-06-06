# Extends Dacte to support CT-e OS documents
import xml.etree.ElementTree as ET
from .dacte import Dacte, extract_text
from .config import DacteConfig
from .dacte_conf import URL


class DacteOS(Dacte):
    """Generate DACTE OS (Outros Serviços) PDF from CT-e OS XML."""

    def __init__(self, xml: str, config: DacteConfig | None = None):
        # Parse XML first so we can insert missing nodes required by base class
        ns_url = URL[URL.find("{") + 1 : URL.find("}")]

        root = ET.fromstring(xml)
        # Rename main tags to match those expected by the base class
        if root.tag.endswith("cteOSProc"):
            root.tag = f"{{{ns_url}}}cteProc"
        cte_os = root.find(f".//{{{ns_url}}}CTeOS")
        if cte_os is not None:
            cte_os.tag = f"{{{ns_url}}}CTe"
        rodo_os = root.find(f".//{{{ns_url}}}rodoOS")
        if rodo_os is not None:
            rodo_os.tag = f"{{{ns_url}}}rodo"
        toma = root.find(f".//{{{ns_url}}}toma")
        if toma is not None:
            toma.tag = f"{{{ns_url}}}toma3"
        ns = {"cte": ns_url}

        # Ensure required nodes exist
        inf_cte = root.find(".//cte:infCte", ns)
        if inf_cte is not None and inf_cte.find("cte:infCarga", ns) is None:
            ET.SubElement(inf_cte, f"{{{ns_url}}}infCarga")
        if inf_cte is not None and inf_cte.find("cte:infDoc", ns) is None:
            ET.SubElement(inf_cte, f"{{{ns_url}}}infDoc")

        xml_fixed = ET.tostring(root, encoding="utf-8").decode()
        super().__init__(xml_fixed, config)

    def _draw_header(self):
        """Draw header adapted for DACTE OS."""
        # Call original implementation then overwrite specific labels
        super()._draw_header()
        # Overwrite main title
        self.set_font(self.default_font, "B", 10)
        self.set_xy(self.l_margin + (self.epw / 2) - 33 - 9, self.y - 49)
        self.multi_cell(w=self.l_margin + (self.epw / 2) - 33, h=4, text="DACTE OS", align="C", border=0)
        # Subtitle
        self.set_font(self.default_font, "", 6)
        self.set_xy(self.l_margin + (self.epw / 2) - 33 - 9, self.y - 45)
        self.multi_cell(
            w=self.l_margin + (self.epw / 2) - 33,
            h=2,
            text="Documento Auxiliar do Conhecimento\nde Transporte Eletrônico para Outros Serviços",
            align="C",
        )

    def _draw_receipt(self):
        """Draw receipt with CT-E OS label."""
        super()._draw_receipt()
        # Replace CT-E label by CT-E OS
        self.set_xy(self.l_margin + (self.epw / 4) * 3 + 23, self.t_margin + 8)
        self.set_font(self.default_font, "B", 10)
        self.cell(w=40, h=-5, text="CT-E OS", border=0, align="L")
