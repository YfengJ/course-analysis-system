import json

from models import (
    AnalysisRevision,
    AnalysisRun,
    AnalysisSnapshot,
    CourseInsight,
    ImportBatch,
    QualitativeRecord,
    Report,
    db,
)


class AnalysisRunService:
    @staticmethod
    def get_record(course_id: int, semester: str, class_scope: str):
        return AnalysisRun.query.filter_by(
            course_id=course_id,
            semester=semester,
            class_scope=class_scope,
        ).first()

    @staticmethod
    def _snapshot_payload(summary):
        if not summary:
            return None
        payload = dict(summary)
        course = payload.get("course")
        if course is not None:
            payload["course"] = {
                "id": getattr(course, "id", None),
                "code": getattr(course, "code", None),
                "name": getattr(course, "name", None),
            }
        return json.dumps(payload, ensure_ascii=False, default=str)

    @classmethod
    def latest_snapshot(cls, course_id: int, semester: str, class_scope: str):
        return (
            AnalysisSnapshot.query.filter_by(
                course_id=course_id,
                semester=semester,
                class_scope=class_scope,
            )
            .order_by(AnalysisSnapshot.version_no.desc(), AnalysisSnapshot.created_at.desc())
            .first()
        )

    @classmethod
    def list_snapshots(cls, course_id: int, semester: str, class_scope: str):
        return (
            AnalysisSnapshot.query.filter_by(
                course_id=course_id,
                semester=semester,
                class_scope=class_scope,
            )
            .order_by(AnalysisSnapshot.version_no.desc(), AnalysisSnapshot.created_at.desc())
            .all()
        )

    @classmethod
    def mark_complete(
        cls,
        course_id: int,
        semester: str,
        class_scope: str,
        student_count: int,
        summary=None,
        source_import_ids=None,
        change_note: str = "系统重新计算",
    ):
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
        latest = cls.latest_snapshot(course_id, semester, class_scope)
        snapshot = AnalysisSnapshot(
            course_id=course_id,
            semester=semester,
            class_scope=class_scope,
            version_no=(latest.version_no + 1) if latest else 1,
            student_count=student_count,
            quantitative_attainment=(summary or {}).get("total_quantitative_attainment", 0.0),
            qualitative_attainment=(summary or {}).get("total_qualitative_attainment", 0.0),
            status=(summary or {}).get("total_status", "已计算"),
            summary_json=cls._snapshot_payload(summary),
            source_import_ids_json=json.dumps(source_import_ids or [], ensure_ascii=False),
            change_note=change_note or "系统重新计算",
        )
        db.session.add(snapshot)
        db.session.commit()
        return record

    @classmethod
    def is_ready(cls, course_id: int, semester: str, class_scope: str) -> bool:
        latest_import = (
            ImportBatch.query.filter_by(course_id=course_id, semester=semester)
            .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
            .first()
        )
        record = cls.get_record(course_id, semester, class_scope)
        if record is not None:
            return not latest_import or record.updated_at >= latest_import.created_at
        latest_report = Report.query.filter_by(
            course_id=course_id,
            semester=semester,
            class_scope=class_scope,
        ).order_by(Report.created_at.desc(), Report.id.desc()).first()
        return bool(latest_report and (not latest_import or latest_report.created_at >= latest_import.created_at))

    @staticmethod
    def invalidate_for_input_change(course_id: int, semester: str | None = None):
        run_query = AnalysisRun.query.filter_by(course_id=course_id)
        revision_query = AnalysisRevision.query.filter_by(course_id=course_id, is_active=True)
        insight_query = CourseInsight.query.filter_by(course_id=course_id)
        qualitative_query = QualitativeRecord.query.filter_by(course_id=course_id)
        if semester:
            run_query = run_query.filter_by(semester=semester)
            revision_query = revision_query.filter_by(semester=semester)
            insight_query = insight_query.filter_by(semester=semester)
            qualitative_query = qualitative_query.filter_by(semester=semester)
        run_query.delete(synchronize_session=False)
        revision_query.update({AnalysisRevision.is_active: False}, synchronize_session=False)
        insight_query.delete(synchronize_session=False)
        qualitative_query.delete(synchronize_session=False)
