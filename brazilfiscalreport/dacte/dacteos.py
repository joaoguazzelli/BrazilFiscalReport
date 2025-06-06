import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from reportlab.lib.units import mm

from brazilfiscalreport.dacte.config import DacteConfig, ReceiptPosition
from brazilfiscalreport.dacte.dacte_conf import (
    TP_CODIGO_MEDIDA_REDUZIDO,
    TP_CTE,
    TP_ICMS,
    TP_MODAL,
    TP_SERVICO,
    TP_TOMADOR,
    URL,
)
from brazilfiscalreport.dacte.generate_qrcode import draw_qr_code
from brazilfiscalreport.utils import (
    format_cep,
    format_cpf_cnpj,
    format_number,
    format_phone,
    get_tag_text,
)
from brazilfiscalreport.xfpdf import xFPDF


@dataclass
class DacteOSLayout:
    """Layout specification for DACTE OS PDF generation."""

    receipt_height: float = 17 * mm
    header_height: float = 70 * mm
    percurso_height: float = 14 * mm
    tomador_height: float = 24 * mm
    service_height: float = 48 * mm
    documents_height: float = 37 * mm
    modal_height: float = 26 * mm
    footer_height: float = 8 * mm


def find_text(element, xpath, namespace=None):
    if element is None:
        return ''
    if namespace is None:
        namespace = {'cte': 'http://www.portalfiscal.inf.br/cte'}

    found = element.find(xpath, namespace)
    if found is not None and found.text is not None:
        return found.text.strip()

    tag_name_without_prefix = xpath.split(':')[-1] if ':' in xpath else xpath
    text_from_tag_helper = get_tag_text(element, URL, tag_name_without_prefix)
    if text_from_tag_helper:
        return text_from_tag_helper.strip()

    return ''


class DacteOS(xFPDF):
    """
    A specialized Dacte class for CT-e OS (Modelo 67) documents,
    inheriting from the base xFPDF and adapting for specific
    XML structures and layout found in DACTE OS.
    """

    def __init__(self, xml_content, config: DacteConfig = None, *, layout: DacteOSLayout | None = None):
        super().__init__(unit="mm", format="A4")
        config = config if config is not None else DacteConfig()
        self.layout = layout if layout is not None else DacteOSLayout()
        self.set_margins(
            left=config.margins.left, top=config.margins.top, right=config.margins.right
        )
        self.set_auto_page_break(auto=False, margin=config.margins.bottom)
        self.set_title("DACTE OS")
        self.logo_image = config.logo
        self.default_font = config.font_type.value
        self.price_precision = config.decimal_config.price_precision
        self.quantity_precision = config.decimal_config.quantity_precision

        # --- Parse XML and find root elements for CT-e OS ---
        root_proc = ET.fromstring(xml_content)
        self.cte_os_node = root_proc.find(f"{URL}CTeOS")
        self.prot_cte_node = root_proc.find(f"{URL}protCTe")

        self.inf_cte = self.cte_os_node.find(f"{URL}infCte")
        self.ide = self.inf_cte.find(f"{URL}ide")
        self.emit = self.inf_cte.find(f"{URL}emit")
        self.toma_node = self.inf_cte.find(f"{URL}toma")
        self.tomador = self.toma_node

        self.v_prest = self.inf_cte.find(f"{URL}vPrest")
        self.imp = self.inf_cte.find(f"{URL}imp")
        self.inf_cte_norm = self.inf_cte.find(f"{URL}infCTeNorm")
        self.inf_carga = self.inf_cte_norm.find(f"{URL}infCarga")
        self.inf_doc = self.inf_cte_norm.find(f"{URL}infDoc")
        self.inf_modal = self.inf_cte_norm.find(f"{URL}infModal")
        self.compl = self.inf_cte.find(f"{URL}compl")
        self.inf_cte_supl = self.inf_cte.find(f"{URL}infCTeSupl")

        self.inf_prot = self.prot_cte_node.find(f"{URL}infProt")

        tpImp = find_text(self.ide, "tpImp")
        if tpImp == "1":
            self.orientation = "P"
        else:
            self.orientation = "L"
            # force receipt position
            # landscape support only left receipt
            self.receipt_pos = ReceiptPosition.LEFT

        # --- Extract and format common data ---
        self.nr_dacte = find_text(self.ide, "nCT")
        self.serie_cte = find_text(self.ide, "serie")
        self.key_cte = self.inf_cte.attrib.get("Id", '').replace('CTe', '')
        self.tp_cte = TP_CTE.get(find_text(self.ide, "tpCTe"), "N/A")
        self.tp_serv = TP_SERVICO.get(find_text(self.ide, "tpServ"), "N/A")

        self.prot_uso = self._get_usage_protocol()

        dh_emi_iso = find_text(self.ide, "dhEmi")
        try:
            dh_emi_obj = datetime.fromisoformat(dh_emi_iso)
            self.dh_emi_formatted = dh_emi_obj.strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            self.dh_emi_formatted = dh_emi_iso

        self.mod = find_text(self.ide, "mod")
        self.cfop = find_text(self.ide, "CFOP")
        self.nat_op = find_text(self.ide, "natOp")

        self.x_mun_ini = find_text(self.ide, "xMunIni")
        self.uf_ini = find_text(self.ide, "UFIni")
        self.x_mun_fim = find_text(self.ide, "xMunFim")
        self.uf_fim = find_text(self.ide, "UFFim")

        # Tomador data
        self.toma_type_code = find_text(self.toma_node, "toma")
        self.toma_desc = TP_TOMADOR.get(self.toma_type_code, "N/A")

        self.tomador_xnome = find_text(self.toma_node, "xNome")
        self.tomador_cnpj_cpf = format_cpf_cnpj(find_text(self.toma_node, "CNPJ"))
        self.tomador_ie = find_text(self.toma_node, "IE")
        self.tomador_xlgr = find_text(self.toma_node.find(f"{URL}enderToma"), "xLgr")
        self.tomador_nro = find_text(self.toma_node.find(f"{URL}enderToma"), "nro")
        self.tomador_xcpl = find_text(self.toma_node.find(f"{URL}enderToma"), "xCpl")
        self.tomador_xbairro = find_text(self.toma_node.find(f"{URL}enderToma"), "xBairro")
        self.tomador_xmun = find_text(self.toma_node.find(f"{URL}enderToma"), "xMun")
        self.tomador_uf = find_text(self.toma_node.find(f"{URL}enderToma"), "UF")
        self.tomador_cep = format_cep(find_text(self.toma_node.find(f"{URL}enderToma"), "CEP"))
        self.tomador_xpais = find_text(self.toma_node.find(f"{URL}enderToma"), "xPais")
        self.tomador_fone = format_phone(find_text(self.toma_node, "fone"))

        # Values
        self.v_tprest = format_number(find_text(self.v_prest, "vTPrest"), self.price_precision)
        self.v_rec = format_number(find_text(self.v_prest, "vRec"), self.price_precision)
        self.comp_list = []
        if self.v_prest is not None:
            for comp in self.v_prest.findall(f"{URL}Comp"):
                self.comp_list.append(
                    (find_text(comp, "xNome"), format_number(find_text(comp, "vComp"), self.price_precision)))

        icms_outra_uf_node = self.imp.find(f"{URL}ICMS/{URL}ICMSOutraUF")
        if icms_outra_uf_node is not None:
            self.icms_cst = find_text(icms_outra_uf_node, "CST")
            self.icms_vbc = format_number(find_text(icms_outra_uf_node, "vBCOutraUF"), self.price_precision)
            self.icms_p_icms = format_number(
                find_text(icms_outra_uf_node, "pFCPUFFim") or find_text(icms_outra_uf_node, "pICMSOutraUF"),
                self.price_precision)
            self.icms_v_icms = format_number(
                find_text(icms_outra_uf_node, "vFCPUFFim") or find_text(icms_outra_uf_node, "vICMSOutraUF"),
                self.price_precision)
            self.icms_pred_bc = "0.00"
            self.icms_st = "0.00"
        else:
            icms_node = self.imp.find(f"{URL}ICMS/{URL}ICMS00")
            if icms_node:
                self.icms_cst = find_text(icms_node, "CST")
                self.icms_vbc = format_number(find_text(icms_node, "vBC"), self.price_precision)
                self.icms_p_icms = format_number(find_text(icms_node, "pICMS"), self.price_precision)
                self.icms_v_icms = format_number(find_text(icms_node, "vICMS"), self.price_precision)
                self.icms_pred_bc = format_number(find_text(icms_node, "pRedBC"), self.price_precision)
                self.icms_st = format_number(find_text(icms_node, "vICMSST"), self.price_precision)
            else:
                self.icms_cst = ""
                self.icms_vbc = "0.00"
                self.icms_p_icms = "0.00"
                self.icms_v_icms = "0.00"
                self.icms_pred_bc = "0.00"
                self.icms_st = "0.00"
        self.cst_desc = TP_ICMS.get(self.icms_cst, "Outros")

        # Service and Cargo Info
        self.x_desc_serv = find_text(self.inf_cte_norm.find(f"{URL}infServico"), "xDescServ")
        self.q_carga = format_number(find_text(self.inf_cte_norm.find(f"{URL}infServico/{URL}infQ"), "qCarga"),
                                     self.quantity_precision)
        self.modal_code = find_text(self.ide, "modal")
        self.modal_desc = TP_MODAL.get(self.modal_code, "N/A")

        self.inf_carga_list = []
        if self.inf_carga is not None:
            for infQ_node in self.inf_carga.findall(f"{URL}infQ"):
                cUnid = find_text(infQ_node, "cUnid")
                tpMed = find_text(infQ_node, "tpMed")
                qCarga_val = find_text(infQ_node, "qCarga")
                self.inf_carga_list.append({
                    'cUnid': cUnid,
                    'tpMed': tpMed,
                    'qCarga': format_number(qCarga_val, self.quantity_precision),
                    'unit_abbr': TP_CODIGO_MEDIDA_REDUZIDO.get(cUnid, '')
                })

        # Documents (chave in infNFe or infCTe within infDoc)
        self.inf_doc_list = []
        if self.inf_doc is not None:
            for nfe_node in self.inf_doc.findall(f"{URL}infNFe"):
                chave = find_text(nfe_node, "chave")
                if chave: self.inf_doc_list.append(chave)
            for cte_node in self.inf_doc.findall(f"{URL}infCTe"):
                chave = find_text(cte_node, "chave")
                if chave: self.inf_doc_list.append(chave)

        self.obs_list = []
        if self.compl is not None:
            xobs_node = self.compl.find(f"{URL}xObs")
            if xobs_node is not None: self.obs_list.append(xobs_node.text.strip())
            for obs_cont_node in self.compl.findall(f"{URL}ObsCont"):
                xtexto_node = obs_cont_node.find(f"{URL}xTexto")
                if xtexto_node is not None: self.obs_list.append(xtexto_node.text.strip())
        self.combined_obs = " ".join(self.obs_list)

        self.rodo_os_node = self.inf_modal.find(f"{URL}rodoOS")
        if self.rodo_os_node is not None:
            self.nro_reg_estadual = find_text(self.rodo_os_node, "NroRegEstadual")
            veic_node = self.rodo_os_node.find(f"{URL}veic")
            if veic_node is not None:
                self.placa_veiculo = find_text(veic_node, "placa")
                self.uf_veiculo = find_text(veic_node, "UF")
        else:
            self.nro_reg_estadual = ""
            self.placa_veiculo = ""
            self.uf_veiculo = ""

        self.qr_code_data = find_text(self.inf_cte_supl, "qrCodCTe")
        self.qr_code_data_unescaped = re.sub(r'&amp;', '&', self.qr_code_data)

        self.c = self
        self.add_page(orientation=self.orientation)

        # The order of drawing methods is crucial for layout
        self._draw_receipt_section()
        self._draw_header_section()
        self._draw_percurso_and_cfop()
        self._draw_tomador_section()
        self._draw_service_info_and_values()
        self._draw_documents_and_observations()
        self._draw_modal_specific_data_rodo_os()
        self._draw_footer_declaration()

        # Watermark (should not appear for production/authorized documents for this XML)
        self._draw_void_watermark_conditional()

    def _draw_receipt_section(self):
        # This is the top receipt part on the DACTE OS
        y_pos = self.t_margin
        box_h = self.layout.receipt_height

        self.c.rect(self.l_margin, y_pos, self.epw, box_h)

        # Receipt text
        self.c.set_font(self.default_font, size=7)
        self.c.set_xy(self.l_margin + 1 * mm, y_pos + 1 * mm)  # Set position before cell
        self.c.cell(w=self.epw - 2 * mm, h=4 * mm, text=self._get_receipt_text(), align='L')  # Use cell for single line

        # Vertical lines for columns in receipt
        col1_x = self.l_margin + 68 * mm
        col2_x = self.l_margin + 158 * mm
        self.c.line(col1_x, y_pos, col1_x, y_pos + box_h)
        self.c.line(col2_x, y_pos, col2_x, y_pos + box_h)

        # Content of receipt columns
        self.c.set_font(self.default_font, size=7)
        self.c.set_xy(self.l_margin + 2 * mm, y_pos + 8 * mm)  # Set position before cell
        self.c.cell(w=60 * mm, h=4 * mm, text="NOME", align='L')
        self.c.set_xy(self.l_margin + 2 * mm, y_pos + 12 * mm)  # Set position before cell
        self.c.cell(w=60 * mm, h=4 * mm, text="RG", align='L')
        self.c.line(self.l_margin + 2 * mm, y_pos + 11 * mm, col1_x - 2 * mm, y_pos + 11 * mm)  # Line for Name
        self.c.line(self.l_margin + 2 * mm, y_pos + 15 * mm, col1_x - 2 * mm, y_pos + 15 * mm)  # Line for RG

        self.c.set_xy(col1_x + 2 * mm, y_pos + 8 * mm)
        self.c.cell(w=80 * mm, h=4 * mm, text="CHEGADA DATA/HORA", align='L')
        self.c.set_xy(col1_x + 2 * mm, y_pos + 12 * mm)
        self.c.cell(w=80 * mm, h=4 * mm, text="SAÍDA DATA/HORA", align='L')
        self.c.line(col1_x + 2 * mm, y_pos + 11 * mm, col2_x - 2 * mm, y_pos + 11 * mm)  # Line for Chegada
        self.c.line(col1_x + 2 * mm, y_pos + 15 * mm, col2_x - 2 * mm, y_pos + 15 * mm)  # Line for Saída

        self.c.set_xy(col2_x + 2 * mm, y_pos + 8 * mm)
        self.c.cell(w=40 * mm, h=4 * mm, text="ASSINATURA/CARIMBO", align='L')

        # CT-e info on receipt (top right)
        self.c.set_font(self.default_font, style='B', size=10)
        self.c.set_xy(col2_x + 2 * mm, y_pos + 1 * mm)
        self.c.cell(w=20 * mm, h=4 * mm, text="CT-E", align='L')
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(col2_x + 35 * mm, y_pos + 1 * mm)
        self.c.cell(w=20 * mm, h=4 * mm, text=self.nr_dacte, align='L')
        self.c.set_xy(col2_x + 48 * mm, y_pos + 1 * mm)
        self.c.cell(w=10 * mm, h=4 * mm, text=self.serie_cte, align='L')

        self.c.set_font(self.default_font, size=7)
        self.c.set_xy(col2_x + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=40 * mm, h=4 * mm, text=f"NRO. DOCUMENTO {self.nr_dacte}", align='L')
        self.c.set_xy(col2_x + 2 * mm, y_pos + 9 * mm)
        self.c.cell(w=40 * mm, h=4 * mm, text=f"SERIE {self.serie_cte}", align='L')

        self.y = y_pos + box_h + 2 * mm

    def _get_receipt_text(self):
        return ("DECLARO QUE RECEBI OS VOLUMES DESTE CONHECIMENTO EM PERFEITO ESTADO PELO QUE DOU POR CUMPRIDO O "
                "PRESENTE CONTRATO DE TRANSPORTE")

    def _draw_header_section(self):
        x_margin = self.l_margin
        y_pos = self.y  # Start from current Y after receipt
        header_height = self.layout.header_height

        # Company Header (TSA TRANSPORTE EXECUTIVO LTDA)
        self.c.rect(x_margin, y_pos, self.epw / 2 - 2 * mm, 33 * mm)  # Left box for emitter info

        # Logo and Name
        if self.logo_image:
            self.c.image(self.logo_image, x_margin + 2 * mm, y_pos + 2 * mm, 12 * mm, 12 * mm, keep_aspect_ratio=True)
            self.c.set_font(self.default_font, style='B', size=10)
            self.c.set_xy(x_margin + 16 * mm, y_pos + 6 * mm)
            self.c.cell(w=40 * mm, h=4 * mm, text=find_text(self.emit, 'xNome').upper(), align='L')
        else:
            self.c.set_font(self.default_font, style='B', size=10)
            self.c.set_xy(x_margin, y_pos + 6 * mm)
            self.c.cell(w=self.epw / 2 - 2 * mm, h=4 * mm, text=find_text(self.emit, 'xNome').upper(), align='C')

        # Emitter Address and Contact
        self.c.set_font(self.default_font, size=8)
        emit_address = f"RUA {find_text(self.emit.find(f'{URL}enderEmit'), 'xLgr')}. {find_text(self.emit.find(f'{URL}enderEmit'), 'nro')}"
        emit_city_state_zip = f"{find_text(self.emit.find(f'{URL}enderEmit'), 'xBairro')}-{format_cep(find_text(self.emit.find(f'{URL}enderEmit'), 'CEP'))}-{find_text(self.emit.find(f'{URL}enderEmit'), 'xMun')}-{find_text(self.emit.find(f'{URL}enderEmit'), 'UF')}"
        emit_phone_fax = f"Fone/Fax: {format_phone(find_text(self.emit.find(f'{URL}enderEmit'), 'fone'))}"
        emit_cnpj_ie = f"CNPJ/CPF: {format_cpf_cnpj(find_text(self.emit, 'CNPJ'))} Insc. Estadual: {find_text(self.emit, 'IE')}"

        self.c.set_xy(x_margin + 2 * mm, y_pos + 12 * mm)
        self.c.cell(w=60 * mm, h=4 * mm, text=emit_address, align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 16 * mm)
        self.c.cell(w=60 * mm, h=4 * mm, text=emit_city_state_zip, align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 20 * mm)
        self.c.cell(w=60 * mm, h=4 * mm, text=emit_phone_fax, align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 24 * mm)
        self.c.cell(w=60 * mm, h=4 * mm, text=emit_cnpj_ie, align='L')

        # DACTE OS Header & Details (right box)
        right_col_x = x_margin + self.epw / 2 - 2 * mm
        self.c.rect(right_col_x, y_pos, self.epw - (right_col_x - x_margin), 33 * mm)  # Right box

        self.c.set_font(self.default_font, style='B', size=12)
        self.c.set_xy(right_col_x, y_pos + 4 * mm)
        self.c.cell(w=self.epw - (right_col_x - x_margin), h=4 * mm, text="DACTE OS", align='C')
        self.c.set_font(self.default_font, size=7)
        self.c.set_xy(right_col_x, y_pos + 7 * mm)
        self.c.multi_cell(w=self.epw - (right_col_x - x_margin), h=3 * mm,
                          text="Documento Auxiliar do Conhecimento\nde Transporte Eletrônico para Outros Serviços",
                          align='C')

        # Model, Series, Number, Date and Time of Emission
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(right_col_x + 2 * mm, y_pos + 13 * mm)
        self.c.cell(w=16 * mm, h=4 * mm, text="MODELO", align='L')
        self.c.set_xy(right_col_x + 18 * mm, y_pos + 13 * mm)
        self.c.cell(w=12 * mm, h=4 * mm, text="SÉRIE", align='L')
        self.c.set_xy(right_col_x + 30 * mm, y_pos + 13 * mm)
        self.c.cell(w=15 * mm, h=4 * mm, text="NÚMERO", align='L')
        self.c.set_xy(right_col_x + 45 * mm, y_pos + 13 * mm)
        self.c.cell(w=30 * mm, h=4 * mm, text="DATA E HORA DE EMISSÃO", align='L')

        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(right_col_x + 2 * mm, y_pos + 17 * mm)
        self.c.cell(w=16 * mm, h=4 * mm, text=self.mod, align='L')
        self.c.set_xy(right_col_x + 18 * mm, y_pos + 17 * mm)
        self.c.cell(w=12 * mm, h=4 * mm, text=self.serie_cte, align='L')
        self.c.set_xy(right_col_x + 30 * mm, y_pos + 17 * mm)
        self.c.cell(w=15 * mm, h=4 * mm, text=self.nr_dacte, align='L')
        self.c.set_xy(right_col_x + 45 * mm, y_pos + 17 * mm)
        self.c.cell(w=30 * mm, h=4 * mm, text=self.dh_emi_formatted, align='L')

        # Tipo do CT-e / Tipo do Serviço
        self.c.set_xy(right_col_x + 2 * mm, y_pos + 22 * mm)
        self.c.cell(w=self.epw - (right_col_x - x_margin) - 4 * mm, h=4 * mm, text=f"TIPO DO CTE: {self.tp_cte}",
                    align='L')
        self.c.set_xy(right_col_x + 2 * mm, y_pos + 26 * mm)
        self.c.cell(w=self.epw - (right_col_x - x_margin) - 4 * mm, h=4 * mm, text=f"TIPO DO SERVIÇO: {self.tp_serv}",
                    align='L')

        # Access Key, Protocol, and QR Code Area
        y_pos_key_qr = y_pos + header_height - 35 * mm
        self.c.rect(x_margin, y_pos_key_qr, self.epw, 35 * mm)  # Box for key and QR code area

        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos_key_qr + 2 * mm)
        self.c.cell(w=40 * mm, h=4 * mm, text="CHAVE DE ACESSO", align='L')
        self.c.set_font(self.default_font, style='B', size=9)
        formatted_key = ' '.join([self.key_cte[i:i + 4] for i in range(0, len(self.key_cte), 4)])
        self.c.set_xy(x_margin + 2 * mm, y_pos_key_qr + 6 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text=formatted_key, align='L')

        self.c.set_font(self.default_font, size=7)
        self.c.set_xy(x_margin + 2 * mm, y_pos_key_qr + 12 * mm)
        self.c.cell(w=100 * mm, h=4 * mm,
                    text="Consulta de autenticidade no portal nacional do CT-e, no site da Sefaz Autorizadora,",
                    align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos_key_qr + 15 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="ou em http://www.cte.fazenda.gov.br", align='L')

        # Protocol
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos_key_qr + 20 * mm)
        self.c.cell(w=60 * mm, h=4 * mm, text="PROTOCOLO DE AUTORIZAÇÃO DE USO", align='L')
        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos_key_qr + 24 * mm)
        self.c.cell(w=60 * mm, h=4 * mm, text=self.prot_uso, align='L')

        # QR Code
        qr_x = x_margin + self.epw - 45 * mm  # Adjust x to place on right side
        qr_y = y_pos_key_qr + 5 * mm
        draw_qr_code(self, self.qr_code_data_unescaped, qr_x, 0, qr_y - self.t_margin,
                     box_size=38)

        self.y = y_pos_key_qr + 35 * mm + 2 * mm

    def _get_usage_protocol(self):
        # Extract protocol from the infProt node
        if self.inf_prot is not None:
            dh_recbto_iso = find_text(self.inf_prot, "dhRecbto")
            dh_recbto_obj = datetime.fromisoformat(dh_recbto_iso)
            dh_recbto_formatted = dh_recbto_obj.strftime("%d/%m/%Y %H:%M:%S")
            nprot = find_text(self.inf_prot, "nProt")
            return f"{nprot}-{dh_recbto_formatted}"
        return "N/A"

    def _draw_percurso_and_cfop(self):
        x_margin = self.l_margin
        y_pos = self.y  # Start from current Y

        self.c.rect(x_margin, y_pos, self.epw, 7 * mm)
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=80 * mm, h=4 * mm, text="CFOP-NATUREZA DA PRESTAÇÃO", align='L')
        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=80 * mm, h=4 * mm, text=f"{self.cfop}-{self.nat_op}", align='L')

        # Right side for Percurso do Veículo / Início / Término
        self.c.line(x_margin + self.epw / 2, y_pos, x_margin + self.epw / 2, y_pos + 7 * mm)  # Vertical line
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + self.epw / 2 + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=80 * mm, h=4 * mm, text="INÍCIO DA PRESTAÇÃO", align='L')
        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(x_margin + self.epw / 2 + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=80 * mm, h=4 * mm, text=f"{self.x_mun_ini}-{self.uf_ini}", align='L')

        y_pos += 7 * mm
        self.c.rect(x_margin, y_pos, self.epw, 7 * mm)
        self.c.line(x_margin + self.epw / 2, y_pos, x_margin + self.epw / 2, y_pos + 7 * mm)  # Vertical line
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=80 * mm, h=4 * mm, text="TÉRMINO DA PRESTAÇÃO", align='L')
        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=80 * mm, h=4 * mm, text=f"{self.x_mun_fim}-{self.uf_fim}", align='L')

        self.y = y_pos + 7 * mm + 2 * mm  # Update current Y position

    def _draw_tomador_section(self):
        x_margin = self.l_margin
        y_pos = self.y  # Start from current Y

        self.c.rect(x_margin, y_pos, self.epw, self.layout.tomador_height)  # Main box for Tomador

        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=40 * mm, h=4 * mm, text="TOMADOR DO SERVIÇO", align='L')
        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(x_margin + 35 * mm, y_pos + 2 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text=self.tomador_xnome, align='L')

        # Address
        address_line_1 = f"ENDEREÇO: {self.tomador_xlgr}, {self.tomador_nro}"
        if self.tomador_xcpl:
            address_line_1 += f"-{self.tomador_xcpl}"
        address_line_1 += f"-{self.tomador_xbairro}"

        address_line_2 = f"MUNICÍPIO: {self.tomador_xmun} UF: {self.tomador_uf} CEP: {self.tomador_cep}"
        address_line_3 = f"PAIS: {self.tomador_xpais} FONE: {self.tomador_fone}"

        self.c.set_xy(x_margin + 2 * mm, y_pos + 6 * mm)
        self.c.cell(w=190 * mm, h=4 * mm, text=address_line_1, align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 10 * mm)
        self.c.cell(w=190 * mm, h=4 * mm, text=f"CNPJ/CPF: {self.tomador_cnpj_cpf}", align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 14 * mm)
        self.c.cell(w=190 * mm, h=4 * mm, text=f"INSCRIÇÃO ESTADUAL: {self.tomador_ie}", align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 18 * mm)
        self.c.cell(w=190 * mm, h=4 * mm, text=address_line_2, align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 22 * mm)
        self.c.cell(w=190 * mm, h=4 * mm, text=address_line_3, align='L')

        self.y = y_pos + self.layout.tomador_height + 2 * mm  # Update current Y

    def _draw_service_info_and_values(self):
        x_margin = self.l_margin
        y_pos = self.y  # Start from current Y

        self.c.rect(x_margin, y_pos, self.epw, 14 * mm)
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=80 * mm, h=4 * mm, text="INFORMAÇÕES DA PRESTAÇÃO DO SERVIÇO", align='L')

        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 6 * mm)
        self.c.cell(w=190 * mm, h=4 * mm, text=f"DESCRIÇÃO DO SERVIÇO PRESTADO: {self.x_desc_serv}", align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 10 * mm)
        self.c.cell(w=190 * mm, h=4 * mm, text=f"QUANTIDADE: {self.q_carga} MODAL: {self.modal_desc}", align='L')

        y_pos += 16 * mm  # Move down
        self.c.rect(x_margin, y_pos, self.epw, 18 * mm)  # Box for components and totals

        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="COMPONENTES DO VALOR DA PRESTAÇÃO DO SERVIÇO", align='L')

        col_width = self.epw / 4  # 4 columns

        # Dynamic components
        comp_y_start = y_pos + 6 * mm
        comp_line_height = 4 * mm

        for i, (name, value) in enumerate(self.comp_list):
            if i >= 6: break  # Max 6 components shown in 3 columns
            col_idx = i % 3
            row_idx = i // 3

            x_comp_name = x_margin + col_idx * col_width
            x_comp_value = x_comp_name + col_width / 2

            current_comp_y = comp_y_start + row_idx * comp_line_height

            self.c.set_font(self.default_font, size=8)
            self.c.set_xy(x_comp_name, current_comp_y)
            self.c.cell(w=col_width / 2, h=4 * mm, text=f"NOME: {name}", align='L')
            self.c.set_xy(x_comp_value, current_comp_y)
            self.c.cell(w=col_width / 2, h=4 * mm, text=f"VALOR: {value}", align='L')

        # Total values (rightmost column)
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 3 * col_width + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=col_width - 4 * mm, h=4 * mm, text="VALOR TOTAL DO SERVIÇO", align='L')
        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(x_margin + 3 * col_width + 2 * mm, y_pos + 6 * mm)
        self.c.cell(w=col_width - 4 * mm, h=4 * mm, text=f"R$ {float(self.v_tprest.replace(',', '.')):.2f}", align='L')

        self.c.set_xy(x_margin + 3 * col_width + 2 * mm, y_pos + 10 * mm)
        self.c.cell(w=col_width - 4 * mm, h=4 * mm, text="VALOR A RECEBER", align='L')
        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(x_margin + 3 * col_width + 2 * mm, y_pos + 14 * mm)
        self.c.cell(w=col_width - 4 * mm, h=4 * mm, text=f"R$ {float(self.v_rec.replace(',', '.')):.2f}", align='L')

        # Vertical lines for columns
        for i in range(1, 4):  # 3 vertical lines for 4 columns
            self.c.line(x_margin + i * col_width, y_pos, x_margin + i * col_width, y_pos + 18 * mm)
        # Horizontal line below "Valor Total do Serviço"
        self.c.line(x_margin + 3 * col_width, y_pos + 8 * mm, x_margin + self.epw, y_pos + 8 * mm)

        y_pos += 20 * mm  # Move down
        self.c.rect(x_margin, y_pos, self.epw, 10 * mm)  # Box for tax info
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="INFORMAÇÕES RELATIVAS AO IMPOSTO", align='L')

        tax_col_width = self.epw / 6  # 6 columns as per DACTE OS
        for i in range(1, 6):  # 5 vertical lines
            self.c.line(x_margin + i * tax_col_width, y_pos, x_margin + i * tax_col_width, y_pos + 10 * mm)

        self.c.set_font(self.default_font, size=7)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text="SITUAÇÃO TRIBUTÁRIA", align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 8 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text=f"{self.icms_cst}-{self.cst_desc}", align='L')

        self.c.set_xy(x_margin + tax_col_width + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text="BASE DE CALCULO", align='L')
        self.c.set_xy(x_margin + tax_col_width + 2 * mm, y_pos + 8 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text=self.icms_vbc, align='L')

        self.c.set_xy(x_margin + 2 * tax_col_width + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text="ALIQ ICMS", align='L')
        self.c.set_xy(x_margin + 2 * tax_col_width + 2 * mm, y_pos + 8 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text=self.icms_p_icms, align='L')

        self.c.set_xy(x_margin + 3 * tax_col_width + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text="VALOR ICMS", align='L')
        self.c.set_xy(x_margin + 3 * tax_col_width + 2 * mm, y_pos + 8 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text=self.icms_v_icms, align='L')

        self.c.set_xy(x_margin + 4 * tax_col_width + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text="% RED. BC ICMS", align='L')
        self.c.set_xy(x_margin + 4 * tax_col_width + 2 * mm, y_pos + 8 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text=self.icms_pred_bc, align='L')

        self.c.set_xy(x_margin + 5 * tax_col_width + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text="ICMS ST", align='L')
        self.c.set_xy(x_margin + 5 * tax_col_width + 2 * mm, y_pos + 8 * mm)
        self.c.cell(w=tax_col_width - 2 * mm, h=4 * mm, text=self.icms_st, align='L')

        self.y = y_pos + 10 * mm + 2 * mm  # Update current Y

    def _draw_documents_and_observations(self):
        x_margin = self.l_margin
        y_pos = self.y  # Start from current Y

        self.c.rect(x_margin, y_pos, self.epw, self.layout.documents_height)  # Box for documents
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="DOCUMENTOS ORIGINÁRIOS", align='L')

        # Columns for documents
        doc_col1_width = 15 * mm  # Tipo Doc
        doc_col2_width = 80 * mm  # CNPJ/Chave
        doc_col3_width = 35 * mm  # Série/Nro. Documento

        current_x = x_margin
        self.c.line(current_x + doc_col1_width, y_pos, current_x + doc_col1_width, y_pos + self.layout.documents_height)
        self.c.line(current_x + doc_col1_width + doc_col2_width, y_pos, current_x + doc_col1_width + doc_col2_width,
                    y_pos + self.layout.documents_height)

        # Headers for document columns
        self.c.set_font(self.default_font, size=7)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=doc_col1_width - 2 * mm, h=4 * mm, text="TIPO DOC", align='L')
        self.c.set_xy(x_margin + doc_col1_width + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=doc_col2_width - 2 * mm, h=4 * mm, text="CNPJ/CHAVE", align='L')
        self.c.set_xy(x_margin + doc_col1_width + doc_col2_width + 2 * mm, y_pos + 5 * mm)
        self.c.cell(w=doc_col3_width - 2 * mm, h=4 * mm, text="SÉRIE/NRO. DOCUMENTO", align='L')

        # Document List (inf_doc_list)
        doc_line_y_start = y_pos + 8 * mm
        line_height = 4 * mm

        for i, chave in enumerate(self.inf_doc_list):
            current_doc_y = doc_line_y_start + i * line_height

            self.c.set_font(self.default_font, style='B', size=7)
            self.c.set_xy(x_margin + 2 * mm, current_doc_y)
            self.c.cell(w=doc_col1_width - 2 * mm, h=4 * mm, text="NFE", align='L')
            self.c.set_xy(x_margin + doc_col1_width + 2 * mm, current_doc_y)
            self.c.cell(w=doc_col2_width - 2 * mm, h=4 * mm, text=chave, align='L')

            # Extract Serie/Nro from Chave
            serie_doc = chave[22:25]
            nro_doc = chave[25:34]
            formatted_nro_doc = f"{int(nro_doc):011,}".replace(",", ".")
            self.c.set_xy(x_margin + doc_col1_width + doc_col2_width + 2 * mm, current_doc_y)
            self.c.cell(w=doc_col3_width - 2 * mm, h=4 * mm, text=f"{serie_doc}/{formatted_nro_doc}", align='L')

        y_pos_obs = y_pos + self.layout.documents_height + 2 * mm  # Move down
        self.c.rect(x_margin, y_pos_obs, self.epw, 10 * mm)  # Box for observations
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos_obs + 2 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="OBSERVAÇÕES GERAIS", align='L')

        self.c.set_font(self.default_font, size=8)
        text_box_y = y_pos_obs + 5 * mm
        text_width = self.epw - 4 * mm  # Small margin inside
        self.c.set_xy(x_margin + 2 * mm, text_box_y)
        self.c.multi_cell(w=text_width, h=3 * mm, text=self.combined_obs, align='L', border=0)

        y_pos_tributos_info = y_pos_obs + 12 * mm  # Adjust Y position below observations
        self.c.set_font(self.default_font, size=7)
        self.c.set_xy(x_margin, y_pos_tributos_info)
        self.c.cell(w=self.epw, h=4 * mm,
                    text="o valor aproximado de tributos incidentes sobre o preço deste serviço é de R$0,00", align='L')

        self.y = y_pos_tributos_info + 4 * mm + 2 * mm  # Update current Y

    def _draw_modal_specific_data_rodo_os(self):
        x_margin = self.l_margin
        y_pos = self.y  # Start from current Y

        self.c.rect(x_margin, y_pos, self.epw, self.layout.modal_height)  # Box for modal specific data
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 2 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="DADOS ESPECÍFICOS DO MODAL RODOVIÁRIO", align='L')

        self.c.set_font(self.default_font, size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos + 6 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text=f"PLACA DO VEÍCULO: {self.placa_veiculo}", align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 10 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text=f"UF: {self.uf_veiculo}", align='L')
        self.c.set_xy(x_margin + 2 * mm, y_pos + 14 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text=f"N DE REGISTRO ESTADUAL: {self.nro_reg_estadual}", align='L')

        # "TERMO DE AUTORIZAÇÃO DE FRETAMENTO" (static text from DACTE OS PDF)
        self.c.set_xy(x_margin + 80 * mm, y_pos + 6 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="TERMO DE AUTORIZAÇÃO DE FRETAMENTO", align='L')
        self.c.set_xy(x_margin + 80 * mm, y_pos + 10 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="", align='L')  # No value provided in XML snippet

        # "USO EXCLUSIVO DO EMISSOR DO CT-E" footer for this section
        y_pos_footer = y_pos + self.layout.modal_height + 2 * mm
        self.c.rect(x_margin, y_pos_footer, self.epw, self.layout.footer_height)
        self.c.set_font(self.default_font, style='B', size=8)
        self.c.set_xy(x_margin + 2 * mm, y_pos_footer + 3 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="USO EXCLUSIVO DO EMISSOR DO CT-E", align='L')

        self.y = y_pos_footer + self.layout.footer_height + 2 * mm  # Update current Y

    def _draw_footer_declaration(self):
        x_margin = self.l_margin
        y_pos = self.y  # Start from current Y

        self.c.set_xy(x_margin, y_pos)
        self.c.cell(w=100 * mm, h=4 * mm, text="TERMINO DA PRESTAÇÃO-DATA/HORA", align='L')
        self.c.set_xy(x_margin + 100 * mm, y_pos)
        self.c.cell(w=100 * mm, h=4 * mm, text="INÍCIO DA PRESTAÇÃO-DATA/HORA", align='L')

        # Print "Impresso em" datetime
        self.c.set_font(self.default_font, size=7)
        self.c.set_xy(x_margin, y_pos + 4 * mm)
        self.c.cell(w=100 * mm, h=4 * mm,
                    text=f"Impresso em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} LuzCon RecebeMais", align='L')
        self.c.set_xy(x_margin + 100 * mm, y_pos + 4 * mm)
        self.c.cell(w=100 * mm, h=4 * mm, text="ASSINATURA/CARIMBO", align='L')

    def _draw_recipient_sender(self, config):
        pass

    def _draw_service_recipient(self, config):
        pass

    def _draw_aereo_info(self, config):
        pass

    def _draw_ferroviario_info(self, config):
        pass

    def _draw_aquaviario_info(self, config):
        pass

    def _draw_multimodal_info(self, config):
        pass

    def _draw_dutoviario_info(self, config):
        pass

    def _draw_modal_specific_data(self, config):
        self._draw_modal_specific_data_rodo_os()

    def _draw_void_watermark_conditional(self):
        is_production_environment = find_text(self.ide, "tpAmb") == "1"
        is_protocol_available = bool(self.inf_prot)

        if not (is_production_environment and is_protocol_available):
            watermark_text = "SEM VALOR FISCAL"
            font_size = 60

            self.c.set_font(self.default_font, style='B', size=font_size)
            width = self.c.get_string_width(watermark_text)
            self.c.set_text_color(r=220, g=150, b=150)
            height = font_size * 0.25
            page_width = self.c.w
            page_height = self.c.h
            x_center = (page_width - width) / 2
            y_center = (page_height + height) / 2
            with self.c.rotation(55, x_center + (width / 2), y_center - (height / 2)):
                self.c.text(x_center, y_center, watermark_text)
            self.c.set_text_color(r=0, g=0, b=0)

    def _add_new_page(self, config):
        pass


