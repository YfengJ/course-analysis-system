import json

from models import AnalysisRevision, db


class AnalysisRevisionService:
    @staticmethod
    def _as_int(value):
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def get_active_revision(cls, course_id: int, semester: str, class_scope: str):
        return (
            AnalysisRevision.query.filter_by(
                course_id=course_id,
                semester=semester,
                class_scope=class_scope,
                is_active=True,
            )
            .order_by(AnalysisRevision.updated_at.desc())
            .first()
        )

    @classmethod
    def save_revision(
        cls,
        course_id: int,
        semester: str,
        class_scope: str,
        qualitative_overrides=None,
        analysis_note: str = "",
        improvement_note: str = "",
        created_by: str = "教师",
    ):
        revision = cls.get_active_revision(course_id, semester, class_scope)
        if not revision:
            revision = AnalysisRevision(
                course_id=course_id,
                semester=semester,
                class_scope=class_scope,
                created_by=created_by or "教师",
                is_active=True,
            )
        revision.qualitative_overrides_json = json.dumps(qualitative_overrides or {}, ensure_ascii=False)
        revision.analysis_note = (analysis_note or "").strip()
        revision.improvement_note = (improvement_note or "").strip()
        revision.created_by = created_by or revision.created_by or "教师"
        db.session.add(revision)
        db.session.commit()
        return revision

    @classmethod
    def payload_from_revision(cls, revision):
        if not revision:
            return None
        try:
            qualitative_overrides = json.loads(revision.qualitative_overrides_json or "{}")
        except json.JSONDecodeError:
            qualitative_overrides = {}
        return {
            "id": revision.id,
            "qualitative_overrides": qualitative_overrides,
            "analysis_note": revision.analysis_note or "",
            "improvement_note": revision.improvement_note or "",
            "created_by": revision.created_by or "教师",
            "updated_at": revision.updated_at,
        }

    @classmethod
    def apply_active_revision(cls, summary, course_id: int, semester: str, class_scope: str):
        revision = cls.get_active_revision(course_id, semester, class_scope)
        return cls.apply_to_summary(summary, revision), cls.payload_from_revision(revision)

    @classmethod
    def apply_to_summary(cls, summary, revision):
        payload = cls.payload_from_revision(revision)
        if not summary or not payload:
            return summary

        overrides = payload["qualitative_overrides"]
        objective_results = summary.get("objective_results") or []
        rows = (summary.get("chapter_four") or {}).get("qualitative_rows") or []
        row_by_title = {row.get("objective_title"): row for row in rows}

        for item in objective_results:
            override = overrides.get(str(item.get("objective_id"))) or overrides.get(item.get("objective_title"))
            if not override:
                continue
            counts = {
                "优": cls._as_int(override.get("excellent_count", override.get("优"))),
                "良": cls._as_int(override.get("good_count", override.get("良"))),
                "中": cls._as_int(override.get("medium_count", override.get("中"))),
                "差": cls._as_int(override.get("poor_count", override.get("差"))),
            }
            total_count = sum(counts.values())
            score_rate = (
                sum(counts[label] * score for label, score in {"优": 90, "良": 80, "中": 70, "差": 60}.items()) / total_count
                if total_count
                else 0.0
            )
            attainment = round(score_rate / 100, 4)
            item["qualitative_counts"] = counts
            item["qualitative_score_percent"] = round(score_rate, 1)
            item["qualitative_attainment"] = attainment
            item["qualitative_rule_note"] = "教师已在计算分析页人工修订该目标的优、良、中、差人数。"

            row = row_by_title.get(item.get("objective_title"))
            if row:
                row.update(
                    {
                        "excellent_count": counts["优"],
                        "good_count": counts["良"],
                        "medium_count": counts["中"],
                        "poor_count": counts["差"],
                        "score_rate": round(score_rate, 1),
                        "attainment": attainment,
                    }
                )

        cls._refresh_total_qualitative(summary)
        summary["analysis_revision"] = payload
        return summary

    @classmethod
    def _refresh_total_qualitative(cls, summary):
        objective_results = summary.get("objective_results") or []
        if not objective_results:
            return
        total_weight = sum(float(item.get("objective_weight") or 0) for item in objective_results) or 1.0
        total_qualitative = round(
            sum(float(item.get("qualitative_attainment") or 0) * (float(item.get("objective_weight") or 0) / total_weight) for item in objective_results),
            4,
        )
        total_score_percent = round(total_qualitative * 100, 1)
        summary["total_qualitative_attainment"] = total_qualitative
        summary["total_qualitative_score_percent"] = total_score_percent

        formula = "+".join(
            f"{float(item.get('qualitative_attainment') or 0):.2f}*{float(item.get('objective_weight') or 0):.0f}%"
            for item in objective_results
        )
        chapter_four = summary.get("chapter_four") or {}
        chapter_four["qualitative_formula"] = f"课程目标达成度={formula}={total_qualitative:.2f}。"
        for row in chapter_four.get("qualitative_rows") or []:
            if row.get("objective_title") == "课程总目标计算":
                row["score_rate"] = total_score_percent
                row["attainment"] = total_qualitative
                break
