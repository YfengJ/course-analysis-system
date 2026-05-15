from models import AnalysisRun, Report, db


class AnalysisRunService:
    @staticmethod
    def get_record(course_id: int, semester: str, class_scope: str):
        return AnalysisRun.query.filter_by(
            course_id=course_id,
            semester=semester,
            class_scope=class_scope,
        ).first()

    @classmethod
    def mark_complete(cls, course_id: int, semester: str, class_scope: str, student_count: int):
        record = cls.get_record(course_id, semester, class_scope)
        if not record:
            record = AnalysisRun(
                course_id=course_id,
                semester=semester,
                class_scope=class_scope,
            )
        record.student_count = student_count
        record.status = "已计算"
        db.session.add(record)
        db.session.commit()
        return record

    @classmethod
    def is_ready(cls, course_id: int, semester: str, class_scope: str) -> bool:
        if cls.get_record(course_id, semester, class_scope) is not None:
            return True
        return Report.query.filter_by(
            course_id=course_id,
            semester=semester,
            class_scope=class_scope,
        ).first() is not None
