import unittest

from docx import Document
from docx.enum.section import WD_SECTION

from services.template_adapters.report_template_adapter import ReportTemplateAdapter


class ReportDocumentLayoutTest(unittest.TestCase):
    def test_report_body_starts_in_a_new_page_section(self):
        document = Document()

        ReportTemplateAdapter._start_body_section(document)

        self.assertEqual(document.sections[-1].start_type, WD_SECTION.NEW_PAGE)


if __name__ == "__main__":
    unittest.main()
