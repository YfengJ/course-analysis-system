from models import AnalysisRun, ImportBatch, Report, Student, TeachingOutline


class CourseProgressService:
    @staticmethod
    def get_latest_outline(course_id: int):
        return TeachingOutline.query.filter_by(course_id=course_id).order_by(TeachingOutline.created_at.desc()).first()

    @staticmethod
    def get_latest_import(course_id: int):
        return ImportBatch.query.filter_by(course_id=course_id).order_by(ImportBatch.created_at.desc()).first()

    @staticmethod
    def get_latest_analysis(course_id: int):
        return AnalysisRun.query.filter_by(course_id=course_id).order_by(AnalysisRun.updated_at.desc()).first()

    @staticmethod
    def get_latest_report(course_id: int):
        return Report.query.filter_by(course_id=course_id).order_by(Report.created_at.desc()).first()

    @staticmethod
    def get_student_count(course) -> int:
        return course.student_count or Student.query.filter_by(course_id=course.id).count()

    @classmethod
    def build_snapshot(cls, course):
        latest_outline = cls.get_latest_outline(course.id)
        latest_import = cls.get_latest_import(course.id)
        latest_analysis = cls.get_latest_analysis(course.id)
        latest_report = cls.get_latest_report(course.id)
        student_count = cls.get_student_count(course)

        outline_ready = latest_outline is not None
        score_ready = student_count > 0
        analysis_ready = latest_analysis is not None or latest_report is not None
        report_ready = latest_report is not None

        if not outline_ready:
            display_status = "待上传大纲"
            next_action = "上传教学大纲"
        elif not score_ready:
            display_status = "待导入成绩"
            next_action = "导入成绩数据"
        elif not analysis_ready:
            display_status = "待计算第四章"
            next_action = "开始计算第四章"
        elif not report_ready:
            display_status = "可预览报告"
            next_action = "查看报告预览"
        else:
            display_status = "已生成报告"
            next_action = "查看最新报告"

        return {
            "latest_outline": latest_outline,
            "latest_import": latest_import,
            "latest_analysis": latest_analysis,
            "latest_report": latest_report,
            "student_count": student_count,
            "outline_ready": outline_ready,
            "score_ready": score_ready,
            "analysis_ready": analysis_ready,
            "report_ready": report_ready,
            "report_preview_ready": analysis_ready,
            "template_ready": outline_ready and score_ready,
            "display_status": display_status,
            "next_action": next_action,
            "status_group": "completed" if report_ready else "pending",
            "stages": [
                {"label": "01 教学大纲", "done": outline_ready},
                {"label": "02 成绩导入", "done": score_ready},
                {"label": "03 计算分析", "done": analysis_ready},
                {"label": "04 报告预览", "done": report_ready},
            ],
            "completed_stage_count": sum(
                1
                for item in [outline_ready, score_ready, analysis_ready, report_ready]
                if item
            ),
        }
