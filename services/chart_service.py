class ChartService:
    @staticmethod
    def build_summary_charts(summary):
        objectives = summary["objective_results"]
        objective_bar = {
            "labels": [item["objective_title"] for item in objectives],
            "quantitative": [round(item["quantitative_attainment"], 4) for item in objectives],
            "qualitative": [round(item["qualitative_attainment"], 4) for item in objectives],
            "expected": summary["course"].expected_value,
        }
        distribution_chart = {
            "labels": list(summary["total_distribution_counts"].keys()),
            "series": [
                {
                    "name": item["objective_title"],
                    "data": [item["distribution_counts"][label] for label in item["distribution_counts"].keys()],
                }
                for item in objectives
            ],
        }
        assessment_bar = {
            "labels": [item["assessment_name"] for item in summary["assessment_performance"]],
            "values": [round(item["score_rate"], 4) for item in summary["assessment_performance"]],
        }
        gauge = {
            "value": round(summary["total_quantitative_attainment"], 4),
            "expected": summary["course"].expected_value,
            "status": summary["total_status"],
        }
        return {
            "objective_bar": objective_bar,
            "distribution_chart": distribution_chart,
            "assessment_bar": assessment_bar,
            "gauge": gauge,
        }
