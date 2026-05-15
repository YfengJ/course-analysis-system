import json
import re
from pathlib import Path

import pandas as pd
from docx import Document
from sqlalchemy import and_
from werkzeug.utils import secure_filename

from models import (
    Assessment,
    Course,
    CourseObjective,
    GraduationRequirement,
    ImportBatch,
    ObjectiveAssessmentWeight,
    ObjectiveRequirementMap,
    ObjectiveScore,
    Score,
    Student,
    TeachingOutline,
    db,
)
from services.template_adapters.outline_template_adapter import OutlineTemplateAdapter
from services.template_adapters.score_template_adapter import ScoreTemplateAdapter


class ImportService:
    STUDENT_COLUMNS = {"序号", "学号", "姓名", "班级", "学期"}
    IGNORED_SCORE_COLUMNS = {"总分", "总成绩", "合计", "总计", "达成度", "达成度(%)", "总达成度(%)"}
    COLUMN_ALIASES = {
        "学号": ["学号", "student_no", "student_id"],
        "姓名": ["姓名", "名字", "name", "学生姓名"],
        "班级": ["班级", "class", "class_name"],
        "学期": ["学期", "semester"],
        "课后作业": ["课后作业", "平时作业", "作业"],
        "大作业": ["大作业", "项目作业", "课程设计"],
        "随堂测试": ["随堂测试", "课堂测试", "小测"],
        "期末考试": ["期末考试", "考试", "期末"],
        "上机实践": ["上机实践", "实验", "上机", "实践"],
    }

    @staticmethod
    def save_upload(file_storage, upload_folder: str) -> Path:
        """保存用户上传文件，统一落到系统上传目录。"""
        upload_dir = Path(upload_folder)
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(file_storage.filename or "upload.dat")
        path = upload_dir / filename
        file_storage.save(path)
        return path

    @classmethod
    def normalize_columns(cls, dataframe: pd.DataFrame) -> pd.DataFrame:
        renamed = {}
        for column in dataframe.columns:
            clean_name = str(column).strip()
            for target, aliases in cls.COLUMN_ALIASES.items():
                if clean_name in aliases:
                    renamed[column] = target
                    break
        return dataframe.rename(columns=renamed)

    @classmethod
    def _read_score_dataframe(cls, file_path: Path) -> pd.DataFrame:
        """读取成绩文件并自动识别包含标准列名的数据表。"""
        adapter_result = ScoreTemplateAdapter.load_score_frame(file_path, cls.normalize_columns)
        return adapter_result["dataframe"]

    @staticmethod
    def _assign_if_blank(course: Course, field_name: str, value):
        """仅在课程字段为空时回填外部解析结果，避免覆盖手工建课信息。"""
        if value in (None, ""):
            return False
        current = getattr(course, field_name, None)
        if current in (None, ""):
            setattr(course, field_name, value)
            return True
        return False

    @staticmethod
    def _assign_from_outline(course: Course, field_name: str, value):
        """教学大纲是课程报告的正式来源，导入后以大纲字段为准。"""
        if value in (None, ""):
            return False
        if getattr(course, field_name, None) != value:
            setattr(course, field_name, value)
            return True
        return False

    @staticmethod
    def _split_requirement_title(raw_title: str):
        text = str(raw_title or "").strip()
        leading = text.replace("\n", " ")
        match = re.match(r"^\s*(\d+)\s*([^\s：:]+)?\s*[：:]?\s*(.*)$", leading)
        if match:
            code = match.group(1)
            title = (match.group(2) or "").strip()
            description = (match.group(3) or "").strip()
            if title:
                return code, title
            if description:
                return code, description[:30]
        if "-" in text:
            code, title = text.split("-", 1)
            return code.strip(), title.strip()
        return text, text

    @staticmethod
    def _safe_float(value, default=0.0):
        if value in (None, ""):
            return default
        try:
            return float(str(value).strip().replace("%", ""))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_assessment_name(value: str) -> str:
        return str(value or "").replace("\n", "").strip()

    @staticmethod
    def _is_placeholder_value(value) -> bool:
        text = str(value or "").strip()
        return text in {"", "待完善", "未命名课程", "占位课程"} or text.startswith("TEMP") or text.startswith("AUTO")

    @classmethod
    def _normalize_objective_ref(cls, value: str) -> str:
        return OutlineTemplateAdapter._normalize_objective_ref(value) or str(value or "").replace(" ", "").strip()

    @classmethod
    def _clear_semester_scores(cls, course: Course, semester: str):
        """同一课程同一学期重新导入成绩时，以本次文件为准，避免旧样例成绩混入计算。"""
        students = Student.query.filter_by(course_id=course.id, semester=semester).all()
        student_ids = [item.id for item in students]
        if not student_ids:
            return
        ObjectiveScore.query.filter(ObjectiveScore.student_id.in_(student_ids)).delete(synchronize_session=False)
        Score.query.filter(Score.student_id.in_(student_ids)).delete(synchronize_session=False)
        Student.query.filter(Student.id.in_(student_ids)).delete(synchronize_session=False)
        db.session.flush()

    @classmethod
    def _sync_requirement_maps(cls, course: Course, parsed_requirements):
        if not parsed_requirements:
            return

        objectives = {
            cls._normalize_objective_ref(objective.title): objective
            for objective in CourseObjective.query.filter_by(course_id=course.id).all()
        }
        for objective in objectives.values():
            ObjectiveRequirementMap.query.filter_by(objective_id=objective.id).delete()
        db.session.flush()

        for item in parsed_requirements:
            objective_ref = cls._normalize_objective_ref(item.get("objective_ref"))
            objective = objectives.get(objective_ref)
            if not objective:
                continue
            code, title = cls._split_requirement_title(item.get("requirement_title", ""))
            indicator_point = (item.get("indicator_point") or "").strip()
            description = (item.get("requirement_description") or "").strip()
            if description.startswith(indicator_point):
                description = description[len(indicator_point):].strip(" ：:，,")
            requirement = GraduationRequirement.query.filter_by(
                code=code,
                indicator_point=indicator_point,
                description=description,
            ).first()
            if not requirement:
                requirement = GraduationRequirement(
                    code=code,
                    title=title,
                    indicator_point=indicator_point,
                    description=description,
                )
                db.session.add(requirement)
                db.session.flush()
            db.session.add(
                ObjectiveRequirementMap(
                    objective_id=objective.id,
                    requirement_id=requirement.id,
                    support_strength=item.get("support_strength") or "M",
                )
            )

    @classmethod
    def _sync_assessment_support(cls, course: Course, assessment_support):
        if not assessment_support:
            return

        objectives = {
            cls._normalize_objective_ref(objective.title): objective
            for objective in CourseObjective.query.filter_by(course_id=course.id).all()
        }
        assessments = {
            cls._normalize_assessment_name(assessment.name): assessment
            for assessment in Assessment.query.filter_by(course_id=course.id).all()
        }
        assessment_totals = {}
        active_assessment_names = []

        for item in assessment_support:
            objective = objectives.get(cls._normalize_objective_ref(item.get("objective_ref")))
            if not objective:
                continue
            objective.weight = cls._safe_float(item.get("objective_weight"), objective.weight)
            old_weight_ids = [
                row.id
                for row in ObjectiveAssessmentWeight.query.with_entities(ObjectiveAssessmentWeight.id)
                .filter_by(objective_id=objective.id)
                .all()
            ]
            if old_weight_ids:
                ObjectiveScore.query.filter(ObjectiveScore.objective_weight_id.in_(old_weight_ids)).delete(
                    synchronize_session=False
                )
                ObjectiveAssessmentWeight.query.filter(ObjectiveAssessmentWeight.id.in_(old_weight_ids)).delete(
                    synchronize_session=False
                )
        db.session.flush()

        next_sequence = len(assessments) + 1
        for item in assessment_support:
            objective = objectives.get(cls._normalize_objective_ref(item.get("objective_ref")))
            if not objective:
                continue
            for mapping in item.get("assessment_map") or []:
                assessment_name = cls._normalize_assessment_name(mapping.get("assessment_name"))
                weight_score = cls._safe_float(mapping.get("weight_score"))
                if not assessment_name or weight_score <= 0:
                    continue
                if assessment_name not in active_assessment_names:
                    active_assessment_names.append(assessment_name)
                assessment = assessments.get(assessment_name)
                if not assessment:
                    assessment = Assessment(
                        course_id=course.id,
                        name=assessment_name,
                        total_score=weight_score,
                        sequence=next_sequence,
                        description=f"{assessment_name}成绩",
                    )
                    db.session.add(assessment)
                    db.session.flush()
                    assessments[assessment_name] = assessment
                    next_sequence += 1
                db.session.add(
                    ObjectiveAssessmentWeight(
                        objective_id=objective.id,
                        assessment_id=assessment.id,
                        weight_score=weight_score,
                    )
                )
                assessment_totals[assessment_name] = assessment_totals.get(assessment_name, 0.0) + weight_score

        for assessment_name, total_score in assessment_totals.items():
            assessments[assessment_name].total_score = total_score
        for sequence, assessment_name in enumerate(active_assessment_names, start=1):
            assessments[assessment_name].sequence = sequence
        for assessment_name, assessment in list(assessments.items()):
            if assessment_name not in active_assessment_names and not assessment.scores:
                db.session.delete(assessment)
        db.session.flush()
        db.session.expire(course, ["assessments"])

    @classmethod
    def _score_columns_from_flat_dataframe(cls, dataframe: pd.DataFrame):
        columns = []
        for column in dataframe.columns:
            name = cls._normalize_assessment_name(column)
            if not name or name.lower() == "nan":
                continue
            if name in cls.STUDENT_COLUMNS or name in cls.IGNORED_SCORE_COLUMNS:
                continue
            if "达成度" in name:
                continue
            numeric = pd.to_numeric(dataframe[column], errors="coerce")
            if numeric.notna().sum() > 0:
                columns.append(name)
        return columns

    @classmethod
    def _split_columns_for_objectives(cls, score_columns, objectives):
        if not objectives:
            return []
        group_count = len(objectives)
        base_size = len(score_columns) // group_count
        remainder = len(score_columns) % group_count
        groups = []
        cursor = 0
        for index, objective in enumerate(objectives):
            size = base_size + (1 if index < remainder else 0)
            if size <= 0 and cursor < len(score_columns):
                size = 1
            groups.append((objective, score_columns[cursor: cursor + size]))
            cursor += size
        return groups

    @classmethod
    def _sync_assessment_support_from_flat_scores(cls, course: Course, dataframe: pd.DataFrame):
        score_columns = cls._score_columns_from_flat_dataframe(dataframe)
        objectives = CourseObjective.query.filter_by(course_id=course.id).order_by(CourseObjective.sequence.asc()).all()
        if not score_columns or not objectives:
            return False

        column_totals = {}
        for column in score_columns:
            numeric = pd.to_numeric(dataframe[column], errors="coerce").dropna()
            column_totals[column] = round(float(numeric.max()), 4) if len(numeric) else 0.0
        if not any(total > 0 for total in column_totals.values()):
            return False

        assessment_support = []
        for objective, columns in cls._split_columns_for_objectives(score_columns, objectives):
            mappings = [
                {"assessment_name": column, "weight_score": column_totals[column]}
                for column in columns
                if column_totals.get(column, 0) > 0
            ]
            if not mappings:
                continue
            assessment_support.append(
                {
                    "objective_ref": objective.title,
                    "objective_weight": sum(item["weight_score"] for item in mappings),
                    "assessment_map": mappings,
                }
            )
        if not assessment_support:
            return False
        cls._sync_assessment_support(course, assessment_support)
        return True

    @classmethod
    def _sync_assessment_support_from_split_payload(cls, course: Course, adapter_result):
        assessment_support = []
        for block in adapter_result.get("objective_blocks") or []:
            assessment_support.append(
                {
                    "objective_ref": block["objective_ref"],
                    "objective_weight": block.get("objective_weight") or sum(item["target_score"] for item in block["items"]),
                    "assessment_map": [
                        {
                            "assessment_name": item["assessment_name"],
                            "weight_score": item["target_score"],
                            "full_score": item.get("full_score"),
                        }
                        for item in block["items"]
                        if item.get("assessment_name") and item.get("target_score", 0) > 0
                    ],
                }
            )
        if assessment_support:
            cls._sync_assessment_support(course, assessment_support)
            return True
        return False

    @staticmethod
    def _validate_score_dataframe(dataframe: pd.DataFrame, course: Course):
        """对成绩表进行完整性与分值区间校验。"""
        issues = []
        required_columns = ["学号"]
        for column in required_columns:
            if column not in dataframe.columns:
                issues.append(f"缺少必要列：{column}")

        assessment_map = {item.name: item.total_score for item in course.assessments}
        seen = set()
        for index, row in dataframe.iterrows():
            row_no = index + 2
            student_no = str(row.get("学号", "")).strip()
            if not student_no:
                issues.append(f"第 {row_no} 行缺少学号")
            elif student_no in seen:
                issues.append(f"第 {row_no} 行学号重复：{student_no}")
            seen.add(student_no)

            for assessment_name, max_score in assessment_map.items():
                if assessment_name not in dataframe.columns:
                    continue
                value = row.get(assessment_name)
                if pd.isna(value):
                    continue
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    issues.append(f"第 {row_no} 行 {assessment_name} 不是有效数字")
                    continue
                if numeric_value < 0 or numeric_value > max_score:
                    issues.append(f"第 {row_no} 行 {assessment_name} 超出允许范围 0-{max_score}")
        return issues

    @staticmethod
    def _normalize_student_name(raw_name: str, student_no: str) -> str:
        clean_name = str(raw_name or "").strip()
        return clean_name or f"学生{student_no}"

    @staticmethod
    def _normalize_class_name(raw_class: str, student_no: str = "") -> str:
        clean_class = str(raw_class or "").strip()
        clean_student_no = str(student_no or "").strip()
        if clean_class and clean_student_no and clean_class == clean_student_no:
            return "未分班"
        return clean_class or "未分班"

    @staticmethod
    def _upsert_student(course: Course, semester: str, student_no: str, name: str, class_name: str):
        student = Student.query.filter_by(
            course_id=course.id,
            student_no=student_no,
            semester=semester,
        ).first()
        if not student:
            student = Student(
                course_id=course.id,
                student_no=student_no,
                name=name,
                class_name=class_name,
                semester=semester,
                major=course.major,
            )
            db.session.add(student)
            db.session.flush()
        else:
            student.name = name or student.name
            student.class_name = class_name or student.class_name
        return student

    @staticmethod
    def _upsert_objective_score(student: Student, objective_weight: ObjectiveAssessmentWeight, score_value: float, original_column: str):
        record = ObjectiveScore.query.filter_by(
            student_id=student.id,
            objective_weight_id=objective_weight.id,
        ).first()
        if not record:
            record = ObjectiveScore(student_id=student.id, objective_weight_id=objective_weight.id)
            db.session.add(record)
        record.score = round(float(score_value), 4)
        record.original_column = original_column
        return record

    @classmethod
    def _build_objective_weight_lookup(cls, course: Course):
        lookup = {}
        objectives = CourseObjective.query.filter_by(course_id=course.id).order_by(CourseObjective.sequence.asc()).all()
        for objective in objectives:
            objective_key = cls._normalize_objective_ref(objective.title)
            lookup[objective_key] = {}
            for weight in objective.assessment_weights:
                lookup[objective_key][weight.assessment.name] = weight
        return lookup

    @classmethod
    def _build_full_score_lookup(cls, adapter_result):
        lookup = {}
        for block in adapter_result.get("objective_blocks") or []:
            objective_ref = cls._normalize_objective_ref(block.get("objective_ref"))
            if not objective_ref:
                continue
            lookup[objective_ref] = {}
            for item in block.get("items") or []:
                assessment_name = item.get("assessment_name")
                full_score = cls._safe_float(item.get("full_score"))
                if assessment_name and full_score > 0:
                    lookup[objective_ref][assessment_name] = full_score
        return lookup

    @classmethod
    def _sync_course_metadata_from_score_payload(cls, course: Course, adapter_result, semester: str):
        metadata = adapter_result.get("metadata") or {}
        if not metadata:
            return

        for field_name, metadata_key in (
            ("code", "course_code"),
            ("name", "course_name"),
            ("nature", "nature"),
            ("assessment_method", "assessment_method"),
            ("course_owner", "course_owner"),
            ("instructors", "instructors"),
        ):
            value = metadata.get(metadata_key)
            if value not in (None, "") and cls._is_placeholder_value(getattr(course, field_name, "")):
                setattr(course, field_name, str(value).strip())

        for field_name in ("hours", "credits"):
            value = metadata.get(field_name)
            if value not in (None, "") and cls._safe_float(value) > 0:
                numeric_value = cls._safe_float(value)
                setattr(course, field_name, int(numeric_value) if field_name == "hours" else numeric_value)

        expected_value = metadata.get("expected_value")
        if expected_value not in (None, "") and cls._safe_float(expected_value) > 0:
            course.expected_value = cls._safe_float(expected_value)

        if metadata.get("semester") and cls._is_placeholder_value(course.semester):
            course.semester = str(metadata["semester"]).strip()
        elif not course.semester and semester:
            course.semester = semester

        if metadata.get("class_names") and cls._is_placeholder_value(course.class_names):
            course.class_names = str(metadata["class_names"]).strip()

    @staticmethod
    def _scale_objective_score(score_value, objective_weight, full_score):
        numeric_score = float(score_value or 0.0)
        target_score = float(objective_weight.weight_score or 0.0)
        full_score = float(full_score or 0.0)
        if full_score > 0:
            return (numeric_score / full_score) * target_score
        return numeric_score

    @classmethod
    def _sync_course_class_names(cls, course: Course, semester: str):
        classes = [
            item.class_name
            for item in Student.query.with_entities(Student.class_name)
            .filter_by(course_id=course.id, semester=semester)
            .order_by(Student.class_name.asc())
            .distinct()
        ]
        class_names = [item for item in classes if item and item != "未分班"]
        if class_names:
            course.class_names = "、".join(class_names)
        else:
            course.class_names = ""

    @classmethod
    def _import_flat_scores(cls, adapter_result, file_path: Path, course: Course, semester: str, reset_semester: bool = True):
        dataframe = adapter_result["dataframe"].copy()
        dataframe = dataframe.astype(object).where(pd.notna(dataframe), "")
        cls._sync_course_metadata_from_score_payload(course, adapter_result, semester)
        recognized_assessments = [item.name for item in course.assessments if item.name in dataframe.columns]
        if not recognized_assessments:
            cls._sync_assessment_support_from_flat_scores(course, dataframe)
        issues = cls._validate_score_dataframe(dataframe, course)
        if not any(item.name in dataframe.columns for item in course.assessments):
            issues.append("未识别到可用于计算的成绩列，请使用系统生成的成绩模板，或上传包含课程目标分项/考核项得分的成绩表。")
        batch = ImportBatch(
            course_id=course.id,
            semester=semester,
            class_scope="全部班级",
            filename=file_path.name,
            source_format=adapter_result["source_format"],
            source_sheet=adapter_result["sheet_name"],
            imported_count=0,
            issue_count=len(issues),
            issues_json=json.dumps(issues, ensure_ascii=False),
            column_mapping_json=json.dumps(adapter_result["mapping"], ensure_ascii=False),
            template_name=ScoreTemplateAdapter.NAME,
            source_template=file_path.name,
        )
        db.session.add(batch)
        if issues:
            db.session.commit()
            return {"success": False, "issues": issues, "imported": 0, "batch": batch}

        assessment_map = {item.name: item for item in course.assessments}
        objective_weight_lookup = cls._build_objective_weight_lookup(course)
        if reset_semester:
            cls._clear_semester_scores(course, semester)
        imported = 0
        for _, row in dataframe.iterrows():
            student_no = str(row["学号"]).strip()
            student = cls._upsert_student(
                course,
                semester,
                student_no,
                cls._normalize_student_name(row.get("姓名", ""), student_no),
                cls._normalize_class_name(row.get("班级", ""), student_no),
            )

            for assessment_name, assessment in assessment_map.items():
                if assessment_name not in dataframe.columns or row[assessment_name] == "":
                    continue
                numeric_value = float(row[assessment_name])
                score = Score.query.filter_by(
                    student_id=student.id,
                    assessment_id=assessment.id,
                ).first()
                if not score:
                    score = Score(student_id=student.id, assessment_id=assessment.id)
                    db.session.add(score)
                score.score = numeric_value
                score.original_column = assessment_name

                for objective_title, weight_map in objective_weight_lookup.items():
                    objective_weight = weight_map.get(assessment_name)
                    if not objective_weight:
                        continue
                    scaled_value = (numeric_value / assessment.total_score) * objective_weight.weight_score if assessment.total_score else 0.0
                    cls._upsert_objective_score(student, objective_weight, scaled_value, assessment_name)

            imported += 1

        course.student_count = Student.query.filter_by(course_id=course.id, semester=semester).count()
        cls._sync_course_class_names(course, semester)
        course.template_source = course.template_source or "课程成绩文件"
        batch.imported_count = imported
        batch.issue_count = 0
        batch.issues_json = json.dumps([], ensure_ascii=False)
        db.session.commit()
        return {"success": True, "issues": [], "imported": imported, "batch": batch}

    @classmethod
    def _import_objective_split_scores(cls, adapter_result, file_path: Path, course: Course, semester: str, reset_semester: bool = True):
        issues = []
        cls._sync_course_metadata_from_score_payload(course, adapter_result, semester)
        cls._sync_assessment_support_from_split_payload(course, adapter_result)
        objective_weight_lookup = cls._build_objective_weight_lookup(course)
        full_score_lookup = cls._build_full_score_lookup(adapter_result)
        assessment_lookup = {item.name: item for item in course.assessments}
        batch = ImportBatch(
            course_id=course.id,
            semester=semester,
            class_scope="全部班级",
            filename=file_path.name,
            source_format=adapter_result["source_format"],
            source_sheet=adapter_result["sheet_name"],
            imported_count=0,
            issue_count=0,
            issues_json=json.dumps([], ensure_ascii=False),
            column_mapping_json=json.dumps(adapter_result["mapping"], ensure_ascii=False),
            template_name=ScoreTemplateAdapter.NAME,
            source_template=file_path.name,
        )
        db.session.add(batch)

        if reset_semester:
            cls._clear_semester_scores(course, semester)
        imported = 0
        for record in adapter_result["records"]:
            student_no = str(record["student_no"]).strip()
            if not student_no:
                issues.append(f"第 {record['row_no']} 行缺少学号")
                continue
            student = cls._upsert_student(
                course,
                semester,
                student_no,
                cls._normalize_student_name(record.get("name", ""), student_no),
                cls._normalize_class_name(record.get("class_name", ""), student_no),
            )
            assessment_totals = {}
            for objective_ref, assessment_scores in record["objective_scores"].items():
                objective_ref = cls._normalize_objective_ref(objective_ref)
                weight_map = objective_weight_lookup.get(objective_ref)
                if not weight_map:
                    issues.append(f"未找到 {objective_ref} 对应的课程目标配置")
                    continue
                for assessment_name, score_value in assessment_scores.items():
                    objective_weight = weight_map.get(assessment_name)
                    if not objective_weight:
                        issues.append(f"{objective_ref} 未配置考核项：{assessment_name}")
                        continue
                    scaled_value = cls._scale_objective_score(
                        score_value,
                        objective_weight,
                        full_score_lookup.get(objective_ref, {}).get(assessment_name),
                    )
                    cls._upsert_objective_score(student, objective_weight, scaled_value, f"{objective_ref}-{assessment_name}")
                    assessment_totals[assessment_name] = assessment_totals.get(assessment_name, 0.0) + float(scaled_value)

            for assessment_name, numeric_value in assessment_totals.items():
                assessment = assessment_lookup.get(assessment_name)
                if not assessment:
                    continue
                score = Score.query.filter_by(student_id=student.id, assessment_id=assessment.id).first()
                if not score:
                    score = Score(student_id=student.id, assessment_id=assessment.id)
                    db.session.add(score)
                score.score = round(numeric_value, 4)
                score.original_column = f"split::{assessment_name}"
            imported += 1

        course.student_count = Student.query.filter_by(course_id=course.id, semester=semester).count()
        cls._sync_course_class_names(course, semester)
        course.template_source = file_path.name
        batch.imported_count = imported
        batch.issue_count = len(issues)
        batch.issues_json = json.dumps(issues, ensure_ascii=False)
        db.session.commit()
        return {"success": len(issues) == 0, "issues": issues, "imported": imported, "batch": batch}

    @classmethod
    def import_scores(cls, file_path: Path, course: Course, semester: str, reset_semester: bool = True):
        """将标准成绩表导入数据库，并按学号执行更新或新增。"""
        file_path = Path(file_path)
        adapter_result = ScoreTemplateAdapter.load_score_payload(file_path, cls.normalize_columns)
        if adapter_result["mode"] == "objective_split":
            return cls._import_objective_split_scores(adapter_result, file_path, course, semester, reset_semester=reset_semester)
        return cls._import_flat_scores(adapter_result, file_path, course, semester, reset_semester=reset_semester)

    @classmethod
    def import_score_files(cls, file_paths, course: Course, semester: str):
        """一次导入多个班级成绩文件，同一学期只清理一次旧成绩，再合并各文件学生记录。"""
        paths = [Path(item) for item in file_paths if item]
        if not paths:
            return {"success": False, "issues": ["请至少选择一个成绩文件。"], "imported": 0, "batches": []}

        cls._clear_semester_scores(course, semester)
        db.session.commit()

        total_imported = 0
        issues = []
        batches = []
        for path in paths:
            result = cls.import_scores(path, course, semester, reset_semester=False)
            total_imported += result.get("imported", 0)
            issues.extend([f"{path.name}：{item}" for item in result.get("issues", [])])
            if result.get("batch"):
                batches.append(result["batch"])

        course.student_count = Student.query.filter_by(course_id=course.id, semester=semester).count()
        cls._sync_course_class_names(course, semester)
        db.session.commit()
        return {"success": not issues, "issues": issues, "imported": total_imported, "batches": batches}

    @staticmethod
    def extract_docx_text(file_path: Path) -> str:
        """提取 docx 文档全文文本，为后续规则解析提供输入。"""
        document = Document(file_path)
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        return "\n".join(paragraphs)

    @classmethod
    def import_outline(cls, file_path: Path, course: Course):
        """导入教学大纲并将解析结果回写到课程与大纲表。"""
        file_path = Path(file_path)
        adapter_result = OutlineTemplateAdapter.extract(file_path)
        raw_text = adapter_result["raw_text"]
        parsed = adapter_result["payload"]
        sync_notes = []

        course.outline_source = file_path.name
        parsed_name = parsed.get("course_name")
        if cls._assign_from_outline(course, "name", parsed_name):
            sync_notes.append(f"课程名称已按教学大纲同步为“{parsed_name}”。")

        parsed_code = parsed.get("course_code")
        duplicate_course = None
        if parsed_code:
            duplicate_course = Course.query.filter(and_(Course.code == parsed_code, Course.id != course.id)).first()
        if parsed_code and duplicate_course:
            sync_notes.append(f"教学大纲中的课程编号“{parsed_code}”已被其他课程占用，系统保留当前课程编号“{course.code}”。")
        elif parsed_code and course.code and parsed_code != course.code:
            old_code = course.code
            course.code = parsed_code
            sync_notes.append(f"课程编号已按教学大纲由“{old_code}”同步为“{parsed_code}”。")
        elif parsed_code:
            cls._assign_from_outline(course, "code", parsed_code)

        field_labels = {
            "major": "适用专业",
            "english_name": "英文名称",
            "nature": "课程性质",
            "category": "课程类别",
            "class_names": "授课班级",
            "department": "开课单位",
            "semester": "开课学期",
            "course_owner": "课程负责人",
            "prerequisites": "先修课程",
            "textbook": "选用教材",
            "description": "课程简介",
            "assessment_method": "考核方式",
        }

        for field_name, payload_key in (
            ("major", "major"),
            ("english_name", "english_name"),
            ("nature", "nature"),
            ("category", "category"),
            ("class_names", "class_names"),
            ("department", "department"),
            ("course_owner", "course_owner"),
            ("prerequisites", "prerequisites"),
            ("textbook", "textbook"),
            ("description", "description"),
            ("assessment_method", "assessment_method"),
        ):
            incoming = parsed.get(payload_key)
            if cls._assign_from_outline(course, field_name, incoming):
                sync_notes.append(f"{field_labels.get(field_name, payload_key)}已按教学大纲同步为“{incoming}”。")

        parsed_semester = parsed.get("semester_hint")
        if parsed_semester:
            current_semester = course.semester or ""
            if current_semester and "学年" in current_semester and "学年" not in parsed_semester:
                sync_notes.append(f"开课学期保留为“{current_semester}”，教学大纲仅提供“{parsed_semester}”。")
            elif cls._assign_from_outline(course, "semester", parsed_semester):
                sync_notes.append(f"开课学期已按教学大纲同步为“{parsed_semester}”。")

        parsed_hours = parsed.get("hours")
        parsed_credits = parsed.get("credits")
        if not parsed_hours and parsed.get("hours_credits") and "/" in parsed["hours_credits"]:
            parsed_hours = parsed["hours_credits"].split("/", 1)[0]
        if not parsed_credits and parsed.get("hours_credits") and "/" in parsed["hours_credits"]:
            parsed_credits = parsed["hours_credits"].split("/", 1)[1]
        if parsed_hours or parsed_credits:
            try:
                if parsed_hours:
                    normalized_hours = int(float(parsed_hours))
                    if course.hours != normalized_hours:
                        course.hours = normalized_hours
                        sync_notes.append(f"学时已按教学大纲同步为“{normalized_hours}”。")
                if parsed_credits:
                    normalized_credits = float(parsed_credits)
                    if course.credits != normalized_credits:
                        course.credits = normalized_credits
                        sync_notes.append(f"学分已按教学大纲同步为“{normalized_credits}”。")
            except (TypeError, ValueError):
                pass
        course.template_name = "教学大纲驱动课程模板"
        course.template_source = file_path.name

        parsed_objectives = parsed.get("objectives") or []
        if parsed_objectives:
            existing_objectives = CourseObjective.query.filter_by(course_id=course.id).order_by(CourseObjective.sequence.asc()).all()
            for index, item in enumerate(parsed_objectives):
                if index < len(existing_objectives):
                    existing_objectives[index].title = item["title"]
                    existing_objectives[index].description = item["description"]
                else:
                    db.session.add(
                        CourseObjective(
                            course_id=course.id,
                            sequence=index + 1,
                            title=item["title"],
                            description=item["description"],
                            weight=0,
                        )
                    )
            db.session.flush()

        cls._sync_requirement_maps(course, parsed.get("requirements") or [])
        cls._sync_assessment_support(course, parsed.get("assessment_support") or [])

        parsed["sync_notes"] = sync_notes
        outline = TeachingOutline(
            course_id=course.id,
            filename=file_path.name,
            raw_text=raw_text,
            parsed_json=json.dumps(parsed, ensure_ascii=False, indent=2),
            summary=adapter_result["summary"],
            parser_name=OutlineTemplateAdapter.NAME,
            parse_status="已解析",
            confidence=parsed.get("confidence", 0.0),
            source_template=file_path.name,
        )
        db.session.add(outline)
        db.session.commit()
        return outline, parsed
