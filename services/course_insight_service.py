import json

from flask import current_app

from models import CourseInsight, ImportBatch, TeachingOutline, db
from services.attainment_service import AttainmentService
from services.llm_service import LLMService


class CourseInsightService:
    PROMPT_VERSION = "course-insight-v2"

    @classmethod
    def get_record(cls, course_id: int, semester: str, class_scope: str):
        return CourseInsight.query.filter_by(
            course_id=course_id,
            semester=semester,
            class_scope=class_scope,
        ).first()

    @classmethod
    def get_payload(cls, course_id: int, semester: str, class_scope: str):
        record = cls.get_record(course_id, semester, class_scope)
        if not record:
            return None
        return cls._deserialize_record(record)

    @classmethod
    def generate_for_scope(cls, course, semester: str, class_scope: str):
        if not LLMService.is_configured():
            raise RuntimeError("尚未配置智能生成服务密钥，暂时无法自动生成课程评价结果。你仍可手工编辑第五章。")

        summary = AttainmentService.calculate(course, semester, class_scope)
        if summary["student_count"] <= 0:
            raise RuntimeError("当前统计范围下暂无成绩数据，请先导入成绩后再生成。")

        outline = TeachingOutline.query.filter_by(course_id=course.id).order_by(TeachingOutline.created_at.desc()).first()
        latest_import = ImportBatch.query.filter_by(course_id=course.id).order_by(ImportBatch.created_at.desc()).first()
        prompt = cls._build_prompt(course, summary, outline, latest_import, semester, class_scope)
        provider = cls._provider_label()
        try:
            generated = LLMService.build_course_insight(prompt)
        except Exception as exc:  # noqa: BLE001
            generated = cls._build_rule_generated_payload(course, summary, exc)
            provider = f"{provider}+规则兜底"
        normalized = cls._normalize_generated_payload(course, summary, generated)

        record = cls.get_record(course.id, semester, class_scope)
        if not record:
            record = CourseInsight(
                course_id=course.id,
                semester=semester,
                class_scope=class_scope,
            )

        record.provider = provider
        record.model_name = current_app.config.get("LLM_MODEL", "")
        record.prompt_version = cls.PROMPT_VERSION
        record.overview_text = normalized["overall_analysis"]
        record.objective_analysis_json = json.dumps(normalized["objective_analyses"], ensure_ascii=False)
        record.improvement_json = json.dumps(normalized["improvement_actions"], ensure_ascii=False)
        record.raw_response_json = json.dumps(generated, ensure_ascii=False)
        db.session.add(record)
        db.session.commit()

        return cls._deserialize_record(record)

    @classmethod
    def save_manual_for_scope(cls, course_id: int, semester: str, class_scope: str, overview_text: str, improvement_text: str):
        """保存教师手工编辑的第五章内容，报告预览和 Word 导出会直接复用。"""
        record = cls.get_record(course_id, semester, class_scope)
        if not record:
            record = CourseInsight(
                course_id=course_id,
                semester=semester,
                class_scope=class_scope,
            )

        overview_text = str(overview_text or "").strip()
        improvement_text = str(improvement_text or "").strip()
        improvement_actions = []
        if improvement_text:
            improvement_actions.append(
                {
                    "title": "教师确认的持续改进措施",
                    "related_objective": "",
                    "problem": overview_text,
                    "action": improvement_text,
                    "expected_effect": "用于下一轮课程教学质量改进与报告归档。",
                    "priority": "中",
                }
            )

        record.provider = "人工编辑"
        record.model_name = "manual"
        record.prompt_version = "manual-v1"
        record.overview_text = overview_text
        record.objective_analysis_json = json.dumps([], ensure_ascii=False)
        record.improvement_json = json.dumps(improvement_actions, ensure_ascii=False)
        record.raw_response_json = json.dumps(
            {
                "source": "manual_edit",
                "overview_text": overview_text,
                "improvement_text": improvement_text,
            },
            ensure_ascii=False,
        )
        db.session.add(record)
        db.session.commit()
        return cls._deserialize_record(record)

    @classmethod
    def _provider_label(cls) -> str:
        base = (current_app.config.get("LLM_API_BASE") or "").lower()
        if "deepseek" in base:
            return "智能生成"
        return "LLM"

    @classmethod
    def _deserialize_record(cls, record):
        return {
            "record": record,
            "overview_text": record.overview_text or "",
            "objective_analyses": json.loads(record.objective_analysis_json or "[]"),
            "improvement_actions": json.loads(record.improvement_json or "[]"),
            "provider": record.provider,
            "model_name": record.model_name,
            "generated_at": record.updated_at or record.created_at,
            "ready": True,
        }

    @classmethod
    def _build_prompt(cls, course, summary, outline, latest_import, semester: str, class_scope: str):
        objective_payload = []
        for item in summary["objective_results"]:
            weakest_assessment = min(
                item["assessment_details"],
                key=lambda detail: detail["score_rate"],
            ) if item["assessment_details"] else None
            strongest_assessment = max(
                item["assessment_details"],
                key=lambda detail: detail["score_rate"],
            ) if item["assessment_details"] else None
            dominant_bucket = max(
                item["distribution_counts"],
                key=item["distribution_counts"].get,
            ) if item["distribution_counts"] else ""
            objective_payload.append(
                {
                    "objective_title": item["objective_title"],
                    "objective_description": cls._limit_text(item["objective_description"], 180),
                    "quantitative_attainment": round(item["quantitative_attainment"], 4),
                    "qualitative_attainment": round(item["qualitative_attainment"], 4),
                    "average_percent": item["statistics"]["average"],
                    "reached_count": item["attainment_snapshot"]["reached_count"],
                    "not_reached_count": item["attainment_snapshot"]["not_reached_count"],
                    "distribution": item["distribution_strings"],
                    "dominant_bucket": dominant_bucket,
                    "weakest_assessment": cls._compact_assessment(weakest_assessment),
                    "strongest_assessment": cls._compact_assessment(strongest_assessment),
                }
            )

        outline_payload = {}
        if outline:
            try:
                outline_payload = json.loads(outline.parsed_json or "{}")
            except json.JSONDecodeError:
                outline_payload = {}

        prompt_payload = {
            "course": {
                "name": course.name,
                "code": course.code,
                "nature": course.nature,
                "category": course.category,
                "hours": course.hours,
                "credits": course.credits,
                "assessment_method": course.assessment_method,
                "course_owner": course.course_owner,
                "semester": semester,
                "class_scope": class_scope,
                "expected_value": course.expected_value,
                "student_count": summary["student_count"],
                "description": cls._limit_text(course.description or outline_payload.get("description", ""), 300),
                "prerequisites": cls._limit_text(course.prerequisites or outline_payload.get("prerequisites", ""), 120),
                "textbook": cls._limit_text(course.textbook or outline_payload.get("textbook", ""), 120),
                "latest_import_file": latest_import.filename if latest_import else "",
            },
            "outline": {
                "summary": cls._limit_text(outline.summary if outline else "", 240),
                "course_description": cls._limit_text(outline_payload.get("description", ""), 300),
                "objectives": outline_payload.get("objectives", []),
                "requirements": [
                    {
                        "indicator_point": item.get("indicator_point", ""),
                        "objective_ref": item.get("objective_ref", ""),
                        "support_strength": item.get("support_strength", ""),
                    }
                    for item in outline_payload.get("requirements", [])
                ],
            },
            "chapter_four_summary": {
                "total_quantitative_attainment": summary["total_quantitative_attainment"],
                "total_qualitative_attainment": summary["total_qualitative_attainment"],
                "total_status": summary["total_status"],
                "assessment_performance": summary["assessment_performance"],
                "qualitative_formula": summary["chapter_four"]["qualitative_formula"],
            },
            "objective_details": objective_payload,
        }

        return "\n".join(
            [
                "请基于以下课程真实数据，生成“第五章 评价结果分析与持续改进措施”的结构化结果。",
                "要求：",
                "1. 必须结合课程本身内容与教学大纲，不要只改写数字。",
                "2. 必须引用第四章里的具体数据，如薄弱考核环节、分布区间、达标人数、目标描述等。",
                "3. 课程是具体课程，不要写成通用工程教育套话。",
                "4. 如果多个目标分数接近，也要根据目标描述、薄弱环节和分布差异写出区别。",
                "5. 改进措施要落到教学活动、作业设计、实验实践、课堂组织或考核方式上，避免空泛表达。",
                "6. 输出必须是合法 JSON 对象，不要添加 Markdown 代码块。",
                "JSON 输出示例结构如下：",
                json.dumps(
                    {
                        "overall_analysis": "2-3段完整中文，概括课程整体达成情况、课程内容特点和主要改进方向",
                        "objective_analyses": [
                            {
                                "objective_title": "课程目标1",
                                "focus_label": "该目标聚焦的知识/能力点",
                                "analysis": "围绕课程内容和数据写 1 段具体分析",
                                "evidence": ["证据1", "证据2", "证据3"],
                                "teaching_suggestion": "与该目标直接相关的后续教学关注点",
                            }
                        ],
                        "improvement_actions": [
                            {
                                "title": "改进措施标题",
                                "related_objective": "课程目标1",
                                "problem": "指出当前问题",
                                "action": "具体教学改进动作",
                                "expected_effect": "期望效果",
                                "priority": "高/中/低",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                "以下是课程数据：",
                json.dumps(prompt_payload, ensure_ascii=False),
            ]
        )

    @staticmethod
    def _limit_text(value, limit: int) -> str:
        text = str(value or "").strip()
        return text[:limit]

    @staticmethod
    def _compact_assessment(assessment):
        if not assessment:
            return None
        return {
            "assessment_name": assessment["assessment_name"],
            "score_rate": assessment["score_rate"],
            "actual_average_percent": assessment["actual_average_percent"],
        }

    @classmethod
    def _build_rule_generated_payload(cls, course, summary, error):
        weakest_assessment = min(
            summary["assessment_performance"],
            key=lambda item: item["score_rate"],
        ) if summary["assessment_performance"] else None
        strongest_assessment = max(
            summary["assessment_performance"],
            key=lambda item: item["score_rate"],
        ) if summary["assessment_performance"] else None

        overall_parts = [
            f"本课程《{course.name}》共有 {summary['student_count']} 名学生参与统计，"
            f"课程总目标定量达成度为 {summary['total_quantitative_attainment']:.2f}，"
            f"定性达成度为 {summary['total_qualitative_attainment']:.2f}，"
            f"课程期望值为 {course.expected_value:.2f}，整体结论为“{summary['total_status']}”。"
        ]
        if weakest_assessment and strongest_assessment:
            overall_parts.append(
                f"从考核环节看，{weakest_assessment['assessment_name']}得分率相对较低"
                f"（{weakest_assessment['score_rate']:.2%}），"
                f"{strongest_assessment['assessment_name']}表现相对较好"
                f"（{strongest_assessment['score_rate']:.2%}）。"
                "后续改进应围绕薄弱环节对应的知识点和训练方式展开，而不是只做泛化复习。"
            )

        objective_analyses = []
        improvement_actions = []
        for objective_result in summary["objective_results"]:
            weakest = min(
                objective_result["assessment_details"],
                key=lambda item: item["score_rate"],
            ) if objective_result["assessment_details"] else None
            focus_label = objective_result["objective_description"][:24]
            objective_analyses.append(
                {
                    "objective_title": objective_result["objective_title"],
                    "focus_label": focus_label,
                    "analysis": cls._fallback_objective_analysis(objective_result),
                    "evidence": cls._fallback_evidence(objective_result),
                    "teaching_suggestion": (
                        f"围绕{weakest['assessment_name']}对应内容增加分层练习和课堂反馈。"
                        if weakest
                        else "继续保持课程目标、课堂训练和评价方式之间的一致性。"
                    ),
                }
            )
            improvement_actions.append(
                {
                    "title": f"{objective_result['objective_title']}薄弱环节强化",
                    "related_objective": objective_result["objective_title"],
                    "problem": (
                        f"{weakest['assessment_name']}得分率为 {weakest['score_rate']:.2%}，"
                        "是该目标下相对薄弱的评价环节。"
                        if weakest
                        else "该目标需要继续通过过程性评价观察学生掌握稳定性。"
                    ),
                    "action": (
                        f"围绕{focus_label}设计一次“示例讲解-课堂练习-课后订正”的闭环任务，"
                        f"并把{weakest['assessment_name'] if weakest else '相关考核'}中的典型错误整理为下一轮教学案例。"
                    ),
                    "expected_effect": "帮助学生把知识理解、操作步骤和工程问题解决过程对应起来，提升目标达成的稳定性。",
                    "priority": "高" if weakest and weakest["score_rate"] < course.expected_value else "中",
                }
            )

        return {
            "overall_analysis": "\n".join(overall_parts),
            "objective_analyses": objective_analyses,
            "improvement_actions": improvement_actions[:5],
            "fallback_reason": str(error),
        }

    @classmethod
    def _normalize_generated_payload(cls, course, summary, payload):
        overall_analysis = str(payload.get("overall_analysis", "")).strip()
        if not overall_analysis:
            raise ValueError("模型未返回整体分析内容")

        raw_objectives = payload.get("objective_analyses") or []
        objective_analyses = []
        for objective_result in summary["objective_results"]:
            matched = cls._match_objective_item(objective_result["objective_title"], raw_objectives)
            evidence = matched.get("evidence") if isinstance(matched.get("evidence"), list) else []
            evidence = [str(item).strip() for item in evidence if str(item).strip()]
            if not evidence:
                evidence = cls._fallback_evidence(objective_result)

            objective_analyses.append(
                {
                    "objective_title": objective_result["objective_title"],
                    "objective_description": objective_result["objective_description"],
                    "focus_label": str(matched.get("focus_label", "")).strip() or objective_result["objective_description"][:24],
                    "analysis": str(matched.get("analysis", "")).strip() or cls._fallback_objective_analysis(objective_result),
                    "evidence": evidence[:3],
                    "teaching_suggestion": str(matched.get("teaching_suggestion", "")).strip(),
                }
            )

        raw_actions = payload.get("improvement_actions") or []
        improvement_actions = []
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            action_text = str(item.get("action", "")).strip()
            title = str(item.get("title", "")).strip()
            if not action_text:
                continue
            improvement_actions.append(
                {
                    "title": title or "持续改进措施",
                    "related_objective": str(item.get("related_objective", "")).strip(),
                    "problem": str(item.get("problem", "")).strip(),
                    "action": action_text,
                    "expected_effect": str(item.get("expected_effect", "")).strip(),
                    "priority": str(item.get("priority", "")).strip() or "中",
                }
            )

        if not improvement_actions:
            raise ValueError("模型未返回改进措施")

        return {
            "overall_analysis": overall_analysis,
            "objective_analyses": objective_analyses,
            "improvement_actions": improvement_actions[:5],
        }

    @staticmethod
    def _match_objective_item(objective_title: str, raw_items):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("objective_title", "")).strip()
            if title == objective_title or objective_title in title or title in objective_title:
                return item
        return {}

    @staticmethod
    def _fallback_evidence(objective_result):
        dominant_bucket = max(
            objective_result["distribution_counts"],
            key=objective_result["distribution_counts"].get,
        ) if objective_result["distribution_counts"] else "无明显集中区间"
        weakest_assessment = min(
            objective_result["assessment_details"],
            key=lambda item: item["score_rate"],
        ) if objective_result["assessment_details"] else None
        evidence = [
            f"定量达成度 {objective_result['quantitative_attainment']:.2f}，定性达成度 {objective_result['qualitative_attainment']:.2f}。",
            f"学生主要分布在 {dominant_bucket} 区间，占比 {objective_result['distribution_rates'].get(dominant_bucket, 0):.2%}。",
        ]
        if weakest_assessment:
            evidence.append(
                f"相对薄弱的考核环节是 {weakest_assessment['assessment_name']}，得分率 {weakest_assessment['score_rate']:.2%}。"
            )
        return evidence

    @staticmethod
    def _fallback_objective_analysis(objective_result):
        weakest_assessment = min(
            objective_result["assessment_details"],
            key=lambda item: item["score_rate"],
        ) if objective_result["assessment_details"] else None
        if weakest_assessment:
            return (
                f"{objective_result['objective_title']}整体已达到课程期望值，但学生表现仍主要集中在中高分区间，"
                f"说明该目标相关能力具备基础达成度，仍需继续围绕{weakest_assessment['assessment_name']}对应的学习活动提升稳定性。"
            )
        return (
            f"{objective_result['objective_title']}整体已达到课程期望值，后续仍应结合课程内容继续强化该目标对应的知识理解与工程实践能力。"
        )
