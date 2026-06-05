from collections import defaultdict
import statistics

from models import (
    Assessment,
    Course,
    CourseObjective,
    ObjectiveScore,
    QualitativeRecord,
    Score,
    Student,
    db,
)


class AttainmentService:
    DISTRIBUTION_LABELS = ["0.90以上", "0.80-0.89", "0.70-0.79", "0.60-0.69", "0.60以下"]
    QUALITATIVE_SCORE_MAP = {"优": 90, "良": 80, "中": 70, "差": 60}

    @staticmethod
    def _distribution_bucket(rate: float) -> str:
        if rate >= 0.9:
            return "0.90以上"
        if rate >= 0.8:
            return "0.80-0.89"
        if rate >= 0.7:
            return "0.70-0.79"
        if rate >= 0.6:
            return "0.60-0.69"
        return "0.60以下"

    @staticmethod
    def _qualitative_bucket(rate: float) -> str:
        if rate >= 0.9:
            return "优"
        if rate >= 0.8:
            return "良"
        if rate >= 0.7:
            return "中"
        return "差"

    @staticmethod
    def _format_distribution_value(count: int, total_count: int) -> str:
        percent = (count / total_count * 100) if total_count else 0.0
        return f"{count} ({percent:.1f}%)"

    @staticmethod
    def _safe_mean(values):
        return statistics.mean(values) if values else 0.0

    @staticmethod
    def _safe_median(values):
        return statistics.median(values) if values else 0.0

    @staticmethod
    def _safe_stdev(values):
        if len(values) <= 1:
            return 0.0
        return statistics.stdev(values)

    @staticmethod
    def _format_formula_number(value, digits=2):
        value = float(value or 0)
        text = f"{value:.{digits}f}"
        return text.rstrip("0").rstrip(".") if "." in text else text

    @classmethod
    def _build_calculation_details(
        cls,
        course,
        objective_results,
        total_quantitative,
        total_qualitative,
        total_quantitative_percent,
        total_qualitative_score_percent,
        total_student_rate_list,
        total_distribution_counts,
        assessment_performance,
        total_formula,
        qualitative_formula,
    ):
        """生成前端可展示的计算过程说明，避免只给结果不交代来源。"""
        quantitative_steps = []
        qualitative_steps = []
        statistics_steps = []
        attainment_steps = []
        distribution_steps = []

        for item in objective_results:
            target_total = sum(detail["target_score"] for detail in item["assessment_details"])
            actual_average_total = sum(detail["actual_average_score"] for detail in item["assessment_details"])
            quantitative_steps.append(
                {
                    "objective_title": item["objective_title"],
                    "title": f"{item['objective_title']}定量达成度",
                    "formula": (
                        f"目标达成度 = 各考核项实际平均分之和 / 该目标分值之和 = "
                        f"{cls._format_formula_number(actual_average_total)} / {cls._format_formula_number(target_total)} "
                        f"= {item['quantitative_attainment']:.2f}"
                    ),
                    "result": f"{item['quantitative_attainment']:.2f}",
                    "details": [
                        (
                            f"{detail['assessment_name']}：实际平均分 {detail['actual_average_score']:.2f}，"
                            f"目标分值 {detail['target_score']:.2f}，"
                            f"得分率 {detail['score_rate']:.2%}"
                        )
                        for detail in item["assessment_details"]
                    ],
                }
            )

            counts = item["qualitative_counts"]
            qualitative_numerator = sum(counts[key] * cls.QUALITATIVE_SCORE_MAP[key] for key in counts)
            qualitative_steps.append(
                {
                    "objective_title": item["objective_title"],
                    "title": f"{item['objective_title']}定性达成度",
                    "formula": (
                        f"得分率 = (优×90 + 良×80 + 中×70 + 差×60) / 学生人数 = "
                        f"({counts['优']}×90 + {counts['良']}×80 + {counts['中']}×70 + {counts['差']}×60) / "
                        f"{len(item['student_rates'])} = {item['qualitative_score_percent']:.1f}"
                    ),
                    "result": f"{item['qualitative_attainment']:.2f}",
                    "details": [
                        item.get("qualitative_rule_note", "划档规则：达成率≥0.90 为优，0.80-0.89 为良，0.70-0.79 为中，低于0.70为差。"),
                        f"定性达成度 = 得分率 / 100 = {item['qualitative_score_percent']:.1f} / 100 = {item['qualitative_attainment']:.2f}",
                        f"赋分合计 = {qualitative_numerator}",
                    ],
                }
            )

            statistics_steps.append(
                {
                    "objective_title": item["objective_title"],
                    "title": f"{item['objective_title']}统计特征",
                    "formula": (
                        f"以 {len(item['student_rate_percents'])} 名学生的该目标达成率为样本，"
                        f"平均值={item['statistics']['average']:.2f}，中位数={item['statistics']['median']:.2f}，"
                        f"标准差={item['statistics']['stddev']:.2f}，最大值={item['statistics']['max']:.2f}，"
                        f"最小值={item['statistics']['min']:.2f}。"
                    ),
                    "result": f"{item['statistics']['average']:.2f}",
                    "details": [
                        "平均值 = 所有学生该课程目标达成率之和 / 学生人数。",
                        "中位数 = 将学生达成率从低到高排序后的中间位置值。",
                        "标准差 = 学生达成率相对平均值的离散程度，系统使用样本标准差计算。",
                    ],
                }
            )

            attainment = item["attainment_snapshot"]
            attainment_steps.append(
                {
                    "objective_title": item["objective_title"],
                    "title": f"{item['objective_title']}达标人数",
                    "formula": (
                        f"达标人数 = 该目标达成率 ≥ 期望值 {attainment['expected_value']:.0f}% 的学生数 = "
                        f"{attainment['reached_count']}；未达标人数 = {len(item['student_rates'])} - "
                        f"{attainment['reached_count']} = {attainment['not_reached_count']}。"
                    ),
                    "result": str(attainment["reached_count"]),
                    "details": [
                        f"超过平均值人数 = 该目标达成率 > 平均值 {item['statistics']['average']:.2f}% 的学生数 = {attainment['above_average_count']}。",
                        f"达成度值展示为该目标平均达成率：{attainment['attainment_value']:.2f}%。",
                    ],
                }
            )

            distribution_steps.append(
                {
                    "objective_title": item["objective_title"],
                    "title": f"{item['objective_title']}区间分布",
                    "formula": "按学生目标达成率落入区间计数：≥0.90、0.80-0.89、0.70-0.79、0.60-0.69、<0.60。",
                    "result": "；".join(f"{label}：{item['distribution_strings'][label]}" for label in cls.DISTRIBUTION_LABELS),
                    "details": [
                        f"{label}：{item['distribution_counts'][label]} 人，占比 {item['distribution_rates'][label]:.2%}"
                        for label in cls.DISTRIBUTION_LABELS
                    ],
                }
            )

        assessment_steps = [
            {
                "title": f"{item['assessment_name']}得分率",
                "formula": (
                    f"得分率 = 该考核项平均得分 / 该考核项总分 = "
                    f"{item['average_score']:.2f} / {item['total_score']:.2f} = {item['score_rate']:.2%}"
                ),
                "result": f"{item['score_rate']:.2%}",
                "details": [
                    f"平均得分来自当前统计范围内 {len(total_student_rate_list)} 名学生该考核项得分的平均值。"
                ],
            }
            for item in assessment_performance
        ]

        return {
            "overview": [
                {
                    "title": "课程总定量达成度",
                    "formula": f"课程总定量达成度 = {total_formula} = {total_quantitative:.2f}",
                    "result": f"{total_quantitative:.2f}",
                    "details": [
                        "每个课程目标先按其关联考核项计算目标达成度，再按课程目标权重加权汇总。",
                        f"百分制展示值为 {total_quantitative_percent:.2f}%。",
                    ],
                },
                {
                    "title": "课程总定性达成度",
                    "formula": f"课程总定性达成度 = {qualitative_formula} = {total_qualitative:.2f}",
                    "result": f"{total_qualitative:.2f}",
                    "details": [
                        "每个课程目标先按优、良、中、差人数赋分得到定性达成度，再按目标权重加权汇总。",
                        f"课程总定性得分率为 {total_qualitative_score_percent:.1f}。",
                    ],
                },
                {
                    "title": "判定结果",
                    "formula": (
                        f"若课程总定量达成度 ≥ 期望值，则判定为达成；"
                        f"当前 {total_quantitative:.2f} {'≥' if total_quantitative >= course.expected_value else '<'} {course.expected_value:.2f}。"
                    ),
                    "result": "达成" if total_quantitative >= course.expected_value else "未达成",
                    "details": [
                        "系统以定量达成度作为最终达成判定依据，定性达成度作为辅助解释。"
                    ],
                },
            ],
            "quantitative_steps": quantitative_steps,
            "qualitative_steps": qualitative_steps,
            "statistics_steps": statistics_steps,
            "attainment_steps": attainment_steps,
            "distribution_steps": distribution_steps,
            "assessment_steps": assessment_steps,
            "total_distribution": {
                "title": "课程总目标区间分布",
                "formula": "按每名学生总课程目标达成率落入区间计数。",
                "result": "；".join(f"{label}：{cls._format_distribution_value(total_distribution_counts[label], len(total_student_rate_list))}" for label in cls.DISTRIBUTION_LABELS),
                "details": [
                    f"{label}：{total_distribution_counts[label]} 人"
                    for label in cls.DISTRIBUTION_LABELS
                ],
            },
        }

    @classmethod
    def _load_students(cls, course_id: int, semester: str, class_scope: str):
        """按课程、学期、班级范围加载学生、通用成绩与分目标成绩。"""
        query = Student.query.filter_by(course_id=course_id, semester=semester)
        if class_scope and class_scope != "全部班级":
            query = query.filter_by(class_name=class_scope)
        students = query.order_by(Student.student_no.asc()).all()
        student_ids = [item.id for item in students]

        raw_scores = []
        objective_scores = []
        if student_ids:
            raw_scores = (
                Score.query.join(Assessment, Assessment.id == Score.assessment_id)
                .filter(Score.student_id.in_(student_ids))
                .all()
            )
            objective_scores = (
                ObjectiveScore.query.filter(ObjectiveScore.student_id.in_(student_ids))
                .all()
            )

        raw_score_map = defaultdict(dict)
        for item in raw_scores:
            raw_score_map[item.student_id][item.assessment_id] = item.score

        objective_score_map = defaultdict(dict)
        for item in objective_scores:
            objective_score_map[item.student_id][item.objective_weight_id] = item.score

        return students, raw_score_map, objective_score_map

    @staticmethod
    def _get_weight_score(student_id, objective_weight, raw_score_map, objective_score_map):
        """优先读取分目标成绩，若不存在则回退到普通成绩按目标权重折算。"""
        stored = objective_score_map.get(student_id, {}).get(objective_weight.id)
        if stored is not None:
            return float(stored)

        raw_score = raw_score_map.get(student_id, {}).get(objective_weight.assessment_id, 0.0)
        assessment_total = objective_weight.assessment.total_score or 0.0
        if assessment_total <= 0:
            return 0.0
        return (float(raw_score) / assessment_total) * objective_weight.weight_score

    @classmethod
    def _build_assessment_detail(cls, students, objective_weight, raw_score_map, objective_score_map):
        student_scores = [
            cls._get_weight_score(student.id, objective_weight, raw_score_map, objective_score_map)
            for student in students
        ]
        average_score = cls._safe_mean(student_scores) if students else 0.0
        target_score = objective_weight.weight_score or 0.0
        average_percent = (average_score / target_score * 100) if target_score else 0.0
        return {
            "assessment_id": objective_weight.assessment_id,
            "assessment_name": objective_weight.assessment.name,
            "percentage_label": f"{target_score:.1f}%",
            "target_score": round(target_score, 2),
            "actual_average_score": round(average_score, 2),
            "actual_average_percent": round(average_percent, 2),
            "score_rate": round(average_percent / 100, 4),
        }

    @classmethod
    def calculate(cls, course: Course, semester: str, class_scope: str = "全部班级"):
        """按照教学大纲与成绩模板配置计算课程目标达成度。"""
        students, raw_score_map, objective_score_map = cls._load_students(course.id, semester, class_scope)
        objectives = CourseObjective.query.filter_by(course_id=course.id).order_by(CourseObjective.sequence.asc()).all()
        assessments = Assessment.query.filter_by(course_id=course.id).order_by(Assessment.sequence.asc()).all()
        total_objective_weight = sum(item.weight for item in objectives) or 1.0
        expected_percent = round((course.expected_value or 0.0) * 100, 2)

        objective_results = []
        total_student_rates = {}
        quantitative_rows = []
        qualitative_rows = []
        statistics_rows = []
        attainment_rows = []

        for objective in objectives:
            weights = sorted(
                objective.assessment_weights,
                key=lambda item: (item.assessment.sequence, item.id),
            )
            objective_target_total = sum(item.weight_score for item in weights) or 1.0
            assessment_details = [
                cls._build_assessment_detail(students, weight, raw_score_map, objective_score_map)
                for weight in weights
            ]

            student_rate_ratios = []
            student_rate_percents = []
            distribution_counts = {label: 0 for label in cls.DISTRIBUTION_LABELS}
            qualitative_counts = {"优": 0, "良": 0, "中": 0, "差": 0}

            for student in students:
                objective_actual_total = sum(
                    cls._get_weight_score(student.id, weight, raw_score_map, objective_score_map)
                    for weight in weights
                )
                objective_rate = objective_actual_total / objective_target_total if objective_target_total else 0.0
                objective_percent = objective_rate * 100
                student_rate_ratios.append(objective_rate)
                student_rate_percents.append(objective_percent)
                distribution_counts[cls._distribution_bucket(objective_rate)] += 1
                qualitative_counts[cls._qualitative_bucket(objective_rate)] += 1
                total_student_rates.setdefault(student.id, 0.0)
                total_student_rates[student.id] += objective_rate * (objective.weight / total_objective_weight)

            quantitative_attainment = round(cls._safe_mean(student_rate_ratios), 4)
            quantitative_attainment_percent = round(cls._safe_mean(student_rate_percents), 2)
            qualitative_score_percent = (
                sum(qualitative_counts[key] * cls.QUALITATIVE_SCORE_MAP[key] for key in qualitative_counts) / len(student_rate_ratios)
                if student_rate_ratios
                else 0.0
            )
            qualitative_attainment = round(qualitative_score_percent / 100, 4)

            average_percent = round(cls._safe_mean(student_rate_percents), 2)
            median_percent = round(cls._safe_median(student_rate_percents), 2)
            stddev_percent = round(cls._safe_stdev(student_rate_percents), 2)
            max_percent = round(max(student_rate_percents), 2) if student_rate_percents else 0.0
            min_percent = round(min(student_rate_percents), 2) if student_rate_percents else 0.0
            reached_count = sum(1 for item in student_rate_percents if item >= expected_percent)
            not_reached_count = len(student_rate_percents) - reached_count
            above_average_count = sum(1 for item in student_rate_percents if item > average_percent)

            distribution_rates = {
                key: round(value / len(student_rate_ratios), 4) if student_rate_ratios else 0.0
                for key, value in distribution_counts.items()
            }
            distribution_strings = {
                key: cls._format_distribution_value(value, len(student_rate_ratios))
                for key, value in distribution_counts.items()
            }

            objective_result = {
                "objective_id": objective.id,
                "objective_title": objective.title,
                "objective_description": objective.description,
                "question_ability": f"{objective.title}：{objective.description}",
                "objective_weight": objective.weight,
                "quantitative_attainment": quantitative_attainment,
                "quantitative_attainment_percent": quantitative_attainment_percent,
                "qualitative_score_percent": round(qualitative_score_percent, 1),
                "qualitative_attainment": qualitative_attainment,
                "status": "达成" if quantitative_attainment >= course.expected_value else "未达成",
                "assessment_details": assessment_details,
                "distribution_counts": distribution_counts,
                "distribution_rates": distribution_rates,
                "distribution_strings": distribution_strings,
                "qualitative_counts": qualitative_counts,
                "student_rates": student_rate_ratios,
                "student_rate_percents": student_rate_percents,
                "statistics": {
                    "average": average_percent,
                    "median": median_percent,
                    "stddev": stddev_percent,
                    "max": max_percent,
                    "min": min_percent,
                },
                "attainment_snapshot": {
                    "expected_value": expected_percent,
                    "attainment_value": quantitative_attainment_percent,
                    "reached_count": reached_count,
                    "not_reached_count": not_reached_count,
                    "above_average_count": above_average_count,
                },
            }
            objective_results.append(objective_result)

            for detail in assessment_details:
                quantitative_rows.append(
                    {
                        "objective_title": objective.title,
                        "assessment_name": detail["assessment_name"],
                        "percentage_label": detail["percentage_label"],
                        "target_score": detail["target_score"],
                        "actual_average_score": detail["actual_average_score"],
                        "actual_average_percent": detail["actual_average_percent"],
                        "objective_weight": round(objective.weight, 2),
                        "objective_attainment": quantitative_attainment,
                        "objective_attainment_percent": quantitative_attainment_percent,
                    }
                )

            qualitative_rows.append(
                {
                    "objective_title": objective.title,
                    "question_ability": objective_result["question_ability"],
                    "excellent_count": qualitative_counts["优"],
                    "good_count": qualitative_counts["良"],
                    "medium_count": qualitative_counts["中"],
                    "poor_count": qualitative_counts["差"],
                    "score_rate": round(qualitative_score_percent, 1),
                    "attainment": qualitative_attainment,
                }
            )

            statistics_rows.append(
                {
                    "objective_title": objective.title,
                    "average": average_percent,
                    "median": median_percent,
                    "stddev": stddev_percent,
                    "max": max_percent,
                    "min": min_percent,
                }
            )

            attainment_rows.append(
                {
                    "objective_title": objective.title,
                    "expected_value": expected_percent,
                    "attainment_value": quantitative_attainment_percent,
                    "reached_count": reached_count,
                    "not_reached_count": not_reached_count,
                    "above_average_count": above_average_count,
                }
            )

        total_student_rate_list = list(total_student_rates.values())
        total_student_rate_percents = [item * 100 for item in total_student_rate_list]
        total_quantitative = round(cls._safe_mean(total_student_rate_list), 4)
        total_quantitative_percent = round(cls._safe_mean(total_student_rate_percents), 2)
        total_distribution_counts = {label: 0 for label in cls.DISTRIBUTION_LABELS}
        total_qualitative_counts = {"优": 0, "良": 0, "中": 0, "差": 0}
        for rate in total_student_rate_list:
            total_distribution_counts[cls._distribution_bucket(rate)] += 1
            total_qualitative_counts[cls._qualitative_bucket(rate)] += 1

        total_qualitative_score_percent = (
            sum(total_qualitative_counts[key] * cls.QUALITATIVE_SCORE_MAP[key] for key in total_qualitative_counts) / len(total_student_rate_list)
            if total_student_rate_list
            else 0.0
        )
        total_qualitative = round(total_qualitative_score_percent / 100, 4)
        total_average_percent = round(cls._safe_mean(total_student_rate_percents), 2)
        total_median_percent = round(cls._safe_median(total_student_rate_percents), 2)
        total_stddev_percent = round(cls._safe_stdev(total_student_rate_percents), 2)
        total_max_percent = round(max(total_student_rate_percents), 2) if total_student_rate_percents else 0.0
        total_min_percent = round(min(total_student_rate_percents), 2) if total_student_rate_percents else 0.0
        total_reached_count = sum(1 for item in total_student_rate_percents if item >= expected_percent)
        total_not_reached_count = len(total_student_rate_percents) - total_reached_count
        total_above_average_count = sum(1 for item in total_student_rate_percents if item > total_average_percent)
        total_distribution_rates = {
            key: round(value / len(total_student_rate_list), 4) if total_student_rate_list else 0.0
            for key, value in total_distribution_counts.items()
        }
        total_distribution_strings = {
            key: cls._format_distribution_value(value, len(total_student_rate_list))
            for key, value in total_distribution_counts.items()
        }

        assessment_performance = []
        for assessment in assessments:
            assessment_totals = []
            for student in students:
                if assessment.objective_weights:
                    total_score = sum(
                        cls._get_weight_score(student.id, item, raw_score_map, objective_score_map)
                        for item in assessment.objective_weights
                    )
                else:
                    total_score = float(raw_score_map.get(student.id, {}).get(assessment.id, 0.0))
                assessment_totals.append(total_score)
            average_score = round(cls._safe_mean(assessment_totals), 2) if students else 0.0
            rate = round((average_score / assessment.total_score), 4) if assessment.total_score else 0.0
            assessment_performance.append(
                {
                    "assessment_name": assessment.name,
                    "average_score": average_score,
                    "total_score": assessment.total_score,
                    "score_rate": rate,
                }
            )

        statistics_rows.append(
            {
                "objective_title": "总目标",
                "average": total_average_percent,
                "median": total_median_percent,
                "stddev": total_stddev_percent,
                "max": total_max_percent,
                "min": total_min_percent,
            }
        )
        attainment_rows.append(
            {
                "objective_title": "总目标",
                "expected_value": expected_percent,
                "attainment_value": total_quantitative_percent,
                "reached_count": total_reached_count,
                "not_reached_count": total_not_reached_count,
                "above_average_count": total_above_average_count,
            }
        )
        qualitative_rows.append(
            {
                "objective_title": "课程总目标计算",
                "question_ability": "课程总目标计算",
                "excellent_count": total_qualitative_counts["优"],
                "good_count": total_qualitative_counts["良"],
                "medium_count": total_qualitative_counts["中"],
                "poor_count": total_qualitative_counts["差"],
                "score_rate": round(total_qualitative_score_percent, 1),
                "attainment": total_qualitative,
            }
        )

        distribution_rows = []
        for item in objective_results:
            distribution_rows.append(
                {
                    "objective_title": item["objective_title"],
                    "buckets": dict(item["distribution_strings"]),
                }
            )
        distribution_rows.append(
            {
                "objective_title": "总目标",
                "buckets": dict(total_distribution_strings),
            }
        )

        total_formula = "+".join(
            f"{item['quantitative_attainment']:.2f}*{item['objective_weight']:.0f}%"
            for item in objective_results
        )
        qualitative_formula = "+".join(
            f"{item['qualitative_attainment']:.2f}*{item['objective_weight']:.0f}%"
            for item in objective_results
        )
        calculation_details = cls._build_calculation_details(
            course,
            objective_results,
            total_quantitative,
            total_qualitative,
            total_quantitative_percent,
            round(total_qualitative_score_percent, 1),
            total_student_rate_list,
            total_distribution_counts,
            assessment_performance,
            total_formula,
            qualitative_formula,
        )

        return {
            "course": course,
            "semester": semester,
            "class_scope": class_scope,
            "student_count": len(students),
            "objective_results": objective_results,
            "total_quantitative_attainment": total_quantitative,
            "total_quantitative_attainment_percent": total_quantitative_percent,
            "total_qualitative_attainment": total_qualitative,
            "total_qualitative_score_percent": round(total_qualitative_score_percent, 1),
            "total_status": "达成" if total_quantitative >= course.expected_value else "未达成",
            "total_distribution_counts": total_distribution_counts,
            "total_distribution_rates": total_distribution_rates,
            "total_distribution_strings": total_distribution_strings,
            "total_qualitative_counts": total_qualitative_counts,
            "assessment_performance": assessment_performance,
            "chapter_four": {
                "quantitative_rows": quantitative_rows,
                "qualitative_rows": qualitative_rows,
                "statistics_rows": statistics_rows,
                "attainment_rows": attainment_rows,
                "distribution_rows": distribution_rows,
                "quantitative_formula": f"课程目标达成度={total_formula}={total_quantitative:.2f}。" if objective_results else "课程目标达成度=0.00。",
                "qualitative_formula": f"课程目标达成度={qualitative_formula}={total_qualitative:.2f}。" if objective_results else "课程目标达成度=0.00。",
                "calculation_details": calculation_details,
            },
        }

    @classmethod
    def save_qualitative_records(cls, summary):
        """将最新一次分析结果中的定性评价写入数据库。"""
        course = summary["course"]
        semester = summary["semester"]
        for item in summary["objective_results"]:
            existing = QualitativeRecord.query.filter_by(
                course_id=course.id,
                objective_id=item["objective_id"],
                semester=semester,
            ).first()
            if not existing:
                existing = QualitativeRecord(
                    course_id=course.id,
                    objective_id=item["objective_id"],
                    semester=semester,
                )
                db.session.add(existing)
            existing.excellent_count = item["qualitative_counts"]["优"]
            existing.good_count = item["qualitative_counts"]["良"]
            existing.medium_count = item["qualitative_counts"]["中"]
            existing.poor_count = item["qualitative_counts"]["差"]
            existing.score_rate = item["qualitative_attainment"]
        db.session.commit()
