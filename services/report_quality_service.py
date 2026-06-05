from models import Assessment, CourseObjective, ImportBatch, Report, Student
from services.analysis_run_service import AnalysisRunService
from services.course_insight_service import CourseInsightService
from services.report_service import ReportService


class ReportQualityService:
    PLACEHOLDER_VALUES = {"", "待完善", "未设置", "未命名课程", "占位课程"}

    @classmethod
    def _is_blank_or_placeholder(cls, value):
        text = str(value or "").strip()
        return text in cls.PLACEHOLDER_VALUES or text.startswith("TEMP") or text.startswith("AUTO")

    @staticmethod
    def _item(level, category, message, suggestion):
        return {
            "level": level,
            "category": category,
            "message": message,
            "suggestion": suggestion,
            "passed": level == "pass",
        }

    @staticmethod
    def _review_level(strict: bool):
        return "error" if strict else "warning"

    @classmethod
    def check_course_report(cls, course, semester: str, class_scope: str, strict: bool = False):
        items = []
        context = ReportService.build_report_context(course, semester, class_scope)
        summary = context["summary"]

        if cls._is_blank_or_placeholder(course.course_owner):
            items.append(cls._item("error", "课程信息", "课程负责人未完善。", "进入课程概览页补充课程负责人。"))
        else:
            items.append(cls._item("pass", "课程信息", "课程负责人已填写。", ""))

        objectives = CourseObjective.query.filter_by(course_id=course.id).order_by(CourseObjective.sequence.asc()).all()
        placeholder_objectives = [
            item
            for item in objectives
            if "请根据课程教学大纲完善" in str(item.description or "") or cls._is_blank_or_placeholder(item.description)
        ]
        if not objectives:
            items.append(cls._item("error", "课程目标", "当前课程还没有课程目标。", "先导入教学大纲或手动维护课程目标。"))
        elif placeholder_objectives:
            items.append(cls._item(cls._review_level(strict), "课程目标", "仍有课程目标使用默认占位描述。", "建议在教学大纲页确认导入正式目标描述。"))
        else:
            items.append(cls._item("pass", "课程目标", "课程目标描述已具备正式内容。", ""))

        mapped_objectives = sum(1 for item in objectives if item.requirement_maps)
        if objectives and mapped_objectives < len(objectives):
            items.append(cls._item(cls._review_level(strict), "毕业要求映射", "部分课程目标缺少毕业要求指标点映射。", "在教学大纲或课程目标配置中补齐支撑关系。"))
        elif objectives:
            items.append(cls._item("pass", "毕业要求映射", "课程目标已配置毕业要求指标点映射。", ""))

        assessments = Assessment.query.filter_by(course_id=course.id).all()
        if not assessments:
            items.append(cls._item("error", "考核配置", "当前课程没有考核项。", "导入教学大纲或维护课程目标与考核权重。"))
        elif any(not item.objective_weights for item in assessments):
            items.append(cls._item(cls._review_level(strict), "考核配置", "部分考核项尚未绑定课程目标权重。", "检查第三章考核支撑关系。"))
        else:
            items.append(cls._item("pass", "考核配置", "考核项与课程目标权重已配置。", ""))

        student_count = summary.get("student_count") or Student.query.filter_by(course_id=course.id, semester=semester).count()
        if student_count <= 0:
            items.append(cls._item("error", "成绩数据", "当前统计范围没有学生成绩。", "先完成成绩导入并确认写入系统。"))
        else:
            items.append(cls._item("pass", "成绩数据", f"当前统计范围共有 {student_count} 名学生。", ""))

        latest_import = ImportBatch.query.filter_by(course_id=course.id, semester=semester).order_by(ImportBatch.created_at.desc()).first()
        if latest_import and (latest_import.issue_count or latest_import.status in {"存在问题", "导入失败"}):
            items.append(cls._item(cls._review_level(strict), "导入日志", "最近一次导入存在异常记录。", "查看成绩导入页的异常摘要并确认是否需要重传。"))
        elif latest_import:
            items.append(cls._item("pass", "导入日志", "最近一次导入未记录异常。", ""))

        if not AnalysisRunService.is_ready(course.id, semester, class_scope):
            items.append(cls._item("error", "计算分析", "第四章达成度计算尚未完成。", "进入计算分析页执行第四章计算。"))
        else:
            items.append(cls._item("pass", "计算分析", "第四章达成度计算已完成。", ""))

        if not context["chapter_five_ready"]:
            items.append(cls._item(cls._review_level(strict), "第五章", "第五章评价结果分析与持续改进措施尚未保存。", "进入第五章编辑页生成或手工保存正式内容。"))
        else:
            provider = (context.get("generated_insight") or {}).get("provider", "已保存")
            items.append(cls._item("pass", "第五章", f"第五章内容已保存，来源：{provider}。", ""))

        not_reached = [
            item
            for item in summary.get("objective_results", [])
            if item.get("quantitative_attainment", 0) < course.expected_value
            or item.get("qualitative_attainment", 0) < course.expected_value
        ]
        if not_reached and not context["chapter_five_ready"]:
            items.append(cls._item(cls._review_level(strict), "持续改进", "存在未达标课程目标，但尚未写入改进措施。", "保存第五章时针对未达标目标补充措施。"))

        latest_report = Report.query.filter_by(course_id=course.id, semester=semester, class_scope=class_scope).order_by(Report.created_at.desc()).first()
        if latest_report and latest_report.is_archived:
            items.append(cls._item("pass", "报告归档", "最新报告已归档为最终版。", ""))
        elif latest_report:
            items.append(cls._item("warning", "报告归档", "最新报告尚未归档为最终版。", "确认无误后在报告预览页归档。"))
        else:
            items.append(cls._item("warning", "报告归档", "当前范围还没有导出的报告版本。", "在报告预览页导出 Word 后再归档。"))

        blocking_count = sum(1 for item in items if item["level"] == "error")
        warning_count = sum(1 for item in items if item["level"] == "warning")
        pass_count = sum(1 for item in items if item["level"] == "pass")
        return {
            "course": course,
            "semester": semester,
            "class_scope": class_scope,
            "items": items,
            "blocking_count": blocking_count,
            "warning_count": warning_count,
            "pass_count": pass_count,
            "ready": blocking_count == 0,
            "strict": strict,
        }
