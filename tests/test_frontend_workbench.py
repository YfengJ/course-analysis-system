from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendWorkbenchContractTest(unittest.TestCase):
    def _read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_base_has_accessible_mobile_navigation(self):
        template = self._read("templates/base.html")

        self.assertIn('class="navbar-toggle"', template)
        self.assertIn('aria-controls="primary-navigation"', template)
        self.assertIn('id="primary-navigation"', template)
        self.assertIn('aria-current="page"', template)

        script = self._read("static/js/app.js")
        self.assertIn('event.key === "Escape"', script)
        self.assertIn("navToggle.focus()", script)

    def test_dashboard_uses_workbench_summary_and_course_queue(self):
        template = self._read("templates/dashboard/index.html")

        self.assertIn('class="workbench-header', template)
        self.assertIn('class="workbench-metrics', template)
        self.assertIn('class="course-queue', template)
        self.assertNotIn('class="poster-hero', template)

    def test_shared_intro_uses_compact_page_header(self):
        template = self._read("templates/partials/page_intro.html")

        self.assertIn('class="page-heading', template)
        self.assertNotIn('class="sub-hero', template)

    def test_report_grid_item_can_shrink_on_mobile(self):
        styles = self._read("static/css/style.css")

        report_rule = re.search(r"\.report-paper\s*\{([^}]*)\}", styles)
        self.assertIsNotNone(report_rule)
        self.assertRegex(report_rule.group(1), r"min-width:\s*0")

        mobile_styles = styles.split("@media (max-width: 767px)", 1)[1]
        mobile_styles = mobile_styles.split("@media (prefers-reduced-motion", 1)[0]
        self.assertIn(".report-paper > .table", mobile_styles)
        self.assertIn("overflow-x: auto", mobile_styles)

    def test_every_post_form_renders_a_csrf_token(self):
        missing = []
        for template_path in (ROOT / "templates").rglob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            for form_html in re.findall(
                r'<form\b[^>]*method=["\']post["\'][^>]*>.*?</form>',
                content,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                if "csrf_token" not in form_html and "hidden_tag()" not in form_html:
                    missing.append(str(template_path.relative_to(ROOT)))

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
