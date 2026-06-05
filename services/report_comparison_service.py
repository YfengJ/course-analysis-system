import json


class ReportComparisonService:
    @staticmethod
    def _load_snapshot(report):
        try:
            return json.loads(report.html_snapshot or "{}")
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _number(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _delta(cls, old_value, new_value):
        return round(cls._number(new_value) - cls._number(old_value), 4)

    @classmethod
    def compare_reports(cls, old_report, new_report):
        old_snapshot = cls._load_snapshot(old_report)
        new_snapshot = cls._load_snapshot(new_report)
        old_objectives = {
            item.get("objective_title"): item
            for item in old_snapshot.get("objective_results", [])
            if item.get("objective_title")
        }
        objective_deltas = []
        for new_item in new_snapshot.get("objective_results", []):
            title = new_item.get("objective_title")
            if not title:
                continue
            old_item = old_objectives.get(title, {})
            objective_deltas.append(
                {
                    "objective_title": title,
                    "old_quantitative": cls._number(old_item.get("quantitative_attainment")),
                    "new_quantitative": cls._number(new_item.get("quantitative_attainment")),
                    "quantitative_delta": cls._delta(old_item.get("quantitative_attainment"), new_item.get("quantitative_attainment")),
                    "old_qualitative": cls._number(old_item.get("qualitative_attainment")),
                    "new_qualitative": cls._number(new_item.get("qualitative_attainment")),
                    "qualitative_delta": cls._delta(old_item.get("qualitative_attainment"), new_item.get("qualitative_attainment")),
                }
            )
        return {
            "old_report": old_report,
            "new_report": new_report,
            "old_snapshot": old_snapshot,
            "new_snapshot": new_snapshot,
            "total_quantitative_delta": cls._delta(
                old_snapshot.get("total_quantitative_attainment"),
                new_snapshot.get("total_quantitative_attainment"),
            ),
            "total_qualitative_delta": cls._delta(
                old_snapshot.get("total_qualitative_attainment"),
                new_snapshot.get("total_qualitative_attainment"),
            ),
            "objective_deltas": objective_deltas,
        }
