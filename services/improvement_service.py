from services.llm_service import LLMService


class ImprovementService:
    @staticmethod
    def build_analysis(summary):
        course = summary["course"]
        objective_results = summary["objective_results"]
        weakest_objective = min(objective_results, key=lambda item: item["quantitative_attainment"]) if objective_results else None
        strongest_objective = max(objective_results, key=lambda item: item["quantitative_attainment"]) if objective_results else None
        weakest_assessment = min(summary["assessment_performance"], key=lambda item: item["score_rate"]) if summary["assessment_performance"] else None
        strongest_assessment = max(summary["assessment_performance"], key=lambda item: item["score_rate"]) if summary["assessment_performance"] else None

        lines = [
            f"从统计结果可得，课程整体定量达成度为 {summary['total_quantitative_attainment']:.2f}，定性达成度为 {summary['total_qualitative_attainment']:.2f}，期望值为 {course.expected_value:.2f}。",
        ]
        if weakest_objective and strongest_objective:
            lines.append(
                f"其中，达成度最高的为{strongest_objective['objective_title']}（{strongest_objective['quantitative_attainment']:.2f}），"
                f"相对较低的为{weakest_objective['objective_title']}（{weakest_objective['quantitative_attainment']:.2f}）。"
            )
        if weakest_assessment and strongest_assessment:
            lines.append(
                f"从考核环节看，{weakest_assessment['assessment_name']}得分率最低（{weakest_assessment['score_rate']:.2%}），"
                f"{strongest_assessment['assessment_name']}得分率最高（{strongest_assessment['score_rate']:.2%}）。"
            )
        return "\n".join(lines)

    @staticmethod
    def build_objective_comment(objective_result):
        distribution = objective_result["distribution_counts"]
        max_bucket = max(distribution, key=distribution.get)
        details = objective_result["assessment_details"]
        best_assessment = max(details, key=lambda item: item["score_rate"]) if details else None
        weak_assessment = min(details, key=lambda item: item["score_rate"]) if details else None

        lines = [
            f"{objective_result['objective_title']}的定量达成度为 {objective_result['quantitative_attainment']:.2f}，"
            f"定性达成度为 {objective_result['qualitative_attainment']:.2f}。",
            f"学生分布以 {max_bucket} 区间为主，占比 {objective_result['distribution_rates'][max_bucket]:.2%}。",
        ]
        if weak_assessment and best_assessment:
            lines.append(
                f"该目标考核中表现最好的环节为{best_assessment['assessment_name']}，"
                f"得分率为 {best_assessment['score_rate']:.2%}；"
                f"相对薄弱的环节为{weak_assessment['assessment_name']}，得分率为 {weak_assessment['score_rate']:.2%}。"
            )
        return " ".join(lines)

    @staticmethod
    def build_rule_based_actions(summary):
        actions = []
        for objective_result in summary["objective_results"]:
            weak_assessment = min(
                objective_result["assessment_details"],
                key=lambda item: item["score_rate"],
            ) if objective_result["assessment_details"] else None
            if not weak_assessment:
                continue

            objective_title = objective_result["objective_title"]
            attainment = objective_result["quantitative_attainment"]
            main_bucket = max(
                objective_result["distribution_counts"],
                key=objective_result["distribution_counts"].get,
            ) if objective_result["distribution_counts"] else None

            if weak_assessment["assessment_name"] == "随堂测试":
                actions.append(
                    f"{objective_title}当前在课堂即时反馈环节相对薄弱，"
                    f"可围绕{main_bucket or '中低分段'}学生补充短时测评、错题复盘和课后追踪，"
                    "把知识点理解、课堂练习和结果反馈串成更紧密的闭环。"
                )
            elif weak_assessment["assessment_name"] in {"上机实践", "大作业"}:
                actions.append(
                    f"{objective_title}在实践任务中的表现还有提升空间，"
                    "可把复杂任务拆成阶段性检查点，并增加典型案例复盘、过程指导和结果讲评，"
                    "帮助学生把原理理解真正转化为操作能力。"
                )
            else:
                actions.append(
                    f"{objective_title}的主要短板集中在{weak_assessment['assessment_name']}，"
                    f"当前定量达成度为{attainment:.2f}。建议围绕典型错题、重点知识点和易混概念组织一次专题讲解，"
                    "同时配合分层辅导，提高学生对核心内容的理解深度。"
                )
        return actions[:3] if actions else [
            "课程整体达成情况较稳定，建议继续保持现有教学组织方式，并结合过程性数据持续观察课堂互动、作业质量和考核区分度。",
            "可在下一轮教学中进一步优化教学活动与考核衔接方式，让课程目标、课堂训练和评价结果之间形成更清晰的对应关系。",
            "建议保留当前表现较好的教学安排，同时针对中间分段学生增加阶段性反馈，帮助更多学生向高达成区间提升。",
        ]

    @classmethod
    def build_improvement_actions(cls, summary):
        fallback_actions = cls.build_rule_based_actions(summary)
        return LLMService.build_improvement_actions(summary, fallback_actions)
