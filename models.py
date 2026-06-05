from datetime import datetime

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Course(TimestampMixin, db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    english_name = db.Column(db.String(128))
    nature = db.Column(db.String(64))
    category = db.Column(db.String(64))
    hours = db.Column(db.Integer, default=32)
    credits = db.Column(db.Float, default=1.5)
    assessment_method = db.Column(db.String(64), default="考查")
    semester = db.Column(db.String(64))
    department = db.Column(db.String(128))
    major = db.Column(db.String(128))
    course_owner = db.Column(db.String(64))
    instructors = db.Column(db.String(255))
    prerequisites = db.Column(db.Text)
    textbook = db.Column(db.Text)
    reference_books = db.Column(db.Text)
    description = db.Column(db.Text)
    expected_value = db.Column(db.Float, default=0.65)
    class_names = db.Column(db.String(255))
    student_count = db.Column(db.Integer, default=0)
    outline_source = db.Column(db.String(255))
    template_name = db.Column(db.String(128), default="通用课程模板")
    template_source = db.Column(db.String(255))
    template_version = db.Column(db.String(64), default="v2")
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    objectives = db.relationship("CourseObjective", backref="course", lazy=True)
    assessments = db.relationship("Assessment", backref="course", lazy=True)
    students = db.relationship("Student", backref="course", lazy=True)
    reports = db.relationship("Report", backref="course", lazy=True)
    insights = db.relationship("CourseInsight", backref="course", lazy=True)
    outlines = db.relationship("TeachingOutline", backref="course", lazy=True)
    import_batches = db.relationship("ImportBatch", backref="course", lazy=True)
    analysis_runs = db.relationship("AnalysisRun", backref="course", lazy=True)
    analysis_snapshots = db.relationship("AnalysisSnapshot", backref="course", lazy=True)
    analysis_revisions = db.relationship("AnalysisRevision", backref="course", lazy=True)


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, unique=True)
    display_name = db.Column(db.String(64), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="teacher")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    courses = db.relationship("Course", backref="owner_user", lazy=True)


class CourseObjective(TimestampMixin, db.Model):
    __tablename__ = "course_objectives"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=1)
    title = db.Column(db.String(64), nullable=False)
    description = db.Column(db.Text, nullable=False)
    weight = db.Column(db.Float, nullable=False, default=0.0)

    requirement_maps = db.relationship(
        "ObjectiveRequirementMap",
        backref="objective",
        lazy=True,
        cascade="all, delete-orphan",
    )
    assessment_weights = db.relationship(
        "ObjectiveAssessmentWeight",
        backref="objective",
        lazy=True,
        cascade="all, delete-orphan",
    )
    qualitative_records = db.relationship("QualitativeRecord", backref="objective", lazy=True)


class GraduationRequirement(TimestampMixin, db.Model):
    __tablename__ = "graduation_requirements"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(128), nullable=False)
    indicator_point = db.Column(db.String(32), nullable=False)
    description = db.Column(db.Text, nullable=False)

    objective_maps = db.relationship(
        "ObjectiveRequirementMap",
        backref="requirement",
        lazy=True,
        cascade="all, delete-orphan",
    )


class ObjectiveRequirementMap(TimestampMixin, db.Model):
    __tablename__ = "objective_requirement_map"

    id = db.Column(db.Integer, primary_key=True)
    objective_id = db.Column(
        db.Integer,
        db.ForeignKey("course_objectives.id"),
        nullable=False,
    )
    requirement_id = db.Column(
        db.Integer,
        db.ForeignKey("graduation_requirements.id"),
        nullable=False,
    )
    support_strength = db.Column(db.String(8), nullable=False, default="M")


class Assessment(TimestampMixin, db.Model):
    __tablename__ = "assessments"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    name = db.Column(db.String(64), nullable=False)
    total_score = db.Column(db.Float, nullable=False, default=100.0)
    description = db.Column(db.String(255))
    sequence = db.Column(db.Integer, nullable=False, default=1)

    objective_weights = db.relationship(
        "ObjectiveAssessmentWeight",
        backref="assessment",
        lazy=True,
        cascade="all, delete-orphan",
    )
    scores = db.relationship("Score", backref="assessment", lazy=True)


class ObjectiveAssessmentWeight(TimestampMixin, db.Model):
    __tablename__ = "objective_assessment_weights"

    id = db.Column(db.Integer, primary_key=True)
    objective_id = db.Column(
        db.Integer,
        db.ForeignKey("course_objectives.id"),
        nullable=False,
    )
    assessment_id = db.Column(
        db.Integer,
        db.ForeignKey("assessments.id"),
        nullable=False,
    )
    weight_score = db.Column(db.Float, nullable=False, default=0.0)
    objective_scores = db.relationship(
        "ObjectiveScore",
        backref="objective_weight",
        lazy=True,
        cascade="all, delete-orphan",
    )


class Student(TimestampMixin, db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    student_no = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(64), nullable=False)
    class_name = db.Column(db.String(64), nullable=False)
    semester = db.Column(db.String(64), nullable=False)
    major = db.Column(db.String(128))

    scores = db.relationship("Score", backref="student", lazy=True, cascade="all, delete-orphan")
    objective_scores = db.relationship("ObjectiveScore", backref="student", lazy=True, cascade="all, delete-orphan")


class Score(TimestampMixin, db.Model):
    __tablename__ = "scores"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessments.id"), nullable=False)
    score = db.Column(db.Float, nullable=False, default=0.0)
    original_column = db.Column(db.String(64))


class ObjectiveScore(TimestampMixin, db.Model):
    __tablename__ = "objective_scores"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    objective_weight_id = db.Column(
        db.Integer,
        db.ForeignKey("objective_assessment_weights.id"),
        nullable=False,
    )
    score = db.Column(db.Float, nullable=False, default=0.0)
    original_column = db.Column(db.String(128))


class QualitativeRecord(TimestampMixin, db.Model):
    __tablename__ = "qualitative_records"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    objective_id = db.Column(
        db.Integer,
        db.ForeignKey("course_objectives.id"),
        nullable=False,
    )
    semester = db.Column(db.String(64), nullable=False)
    excellent_count = db.Column(db.Integer, default=0)
    good_count = db.Column(db.Integer, default=0)
    medium_count = db.Column(db.Integer, default=0)
    poor_count = db.Column(db.Integer, default=0)
    score_rate = db.Column(db.Float, default=0.0)


class TeachingOutline(TimestampMixin, db.Model):
    __tablename__ = "teaching_outlines"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    raw_text = db.Column(db.Text)
    parsed_json = db.Column(db.Text)
    summary = db.Column(db.Text)
    parser_name = db.Column(db.String(128), default="outline_template_adapter")
    parse_status = db.Column(db.String(32), default="已解析")
    confidence = db.Column(db.Float, default=0.0)
    source_template = db.Column(db.String(255))


class ImportBatch(TimestampMixin, db.Model):
    __tablename__ = "import_batches"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    semester = db.Column(db.String(64), nullable=False)
    class_scope = db.Column(db.String(255), default="全部班级")
    filename = db.Column(db.String(255), nullable=False)
    source_format = db.Column(db.String(32), nullable=False, default="excel")
    source_sheet = db.Column(db.String(128))
    imported_count = db.Column(db.Integer, default=0)
    issue_count = db.Column(db.Integer, default=0)
    issues_json = db.Column(db.Text)
    column_mapping_json = db.Column(db.Text)
    template_name = db.Column(db.String(128), default="score_template_adapter")
    source_template = db.Column(db.String(255))
    import_version = db.Column(db.Integer, default=1)
    file_hash = db.Column(db.String(64))
    source_files_json = db.Column(db.Text)
    pre_student_count = db.Column(db.Integer, default=0)
    post_student_count = db.Column(db.Integer, default=0)
    cleanup_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(32), default="已完成")
    notes = db.Column(db.Text)


class AnalysisRun(TimestampMixin, db.Model):
    __tablename__ = "analysis_runs"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    semester = db.Column(db.String(64), nullable=False)
    class_scope = db.Column(db.String(255), nullable=False, default="全部班级")
    student_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(32), nullable=False, default="已计算")

    __table_args__ = (
        db.UniqueConstraint("course_id", "semester", "class_scope", name="uq_analysis_run_scope"),
    )


class AnalysisSnapshot(TimestampMixin, db.Model):
    __tablename__ = "analysis_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    semester = db.Column(db.String(64), nullable=False)
    class_scope = db.Column(db.String(255), nullable=False, default="全部班级")
    version_no = db.Column(db.Integer, nullable=False, default=1)
    student_count = db.Column(db.Integer, default=0)
    quantitative_attainment = db.Column(db.Float, nullable=False, default=0.0)
    qualitative_attainment = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(32), nullable=False, default="已计算")
    summary_json = db.Column(db.Text)
    source_import_ids_json = db.Column(db.Text)
    change_note = db.Column(db.String(255), default="系统重新计算")

    __table_args__ = (
        db.UniqueConstraint("course_id", "semester", "class_scope", "version_no", name="uq_analysis_snapshot_version"),
    )


class AnalysisRevision(TimestampMixin, db.Model):
    __tablename__ = "analysis_revisions"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    semester = db.Column(db.String(64), nullable=False)
    class_scope = db.Column(db.String(255), nullable=False, default="全部班级")
    qualitative_overrides_json = db.Column(db.Text)
    analysis_note = db.Column(db.Text)
    improvement_note = db.Column(db.Text)
    created_by = db.Column(db.String(64), default="教师")
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Report(TimestampMixin, db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    semester = db.Column(db.String(64), nullable=False)
    class_scope = db.Column(db.String(255), nullable=False, default="全部班级")
    quantitative_attainment = db.Column(db.Float, nullable=False, default=0.0)
    qualitative_attainment = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(32), nullable=False, default="未达成")
    word_path = db.Column(db.String(255))
    html_snapshot = db.Column(db.Text)
    summary_text = db.Column(db.Text)
    improvement_text = db.Column(db.Text)
    template_name = db.Column(db.String(128), default="report_template_adapter")
    template_version = db.Column(db.String(64), default="v2")
    source_template = db.Column(db.String(255))
    analysis_snapshot_id = db.Column(db.Integer, db.ForeignKey("analysis_snapshots.id"))
    report_version = db.Column(db.Integer, default=1)
    comparison_base_report_id = db.Column(db.Integer)
    source_import_ids_json = db.Column(db.Text)
    change_note = db.Column(db.String(255))
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    archived_at = db.Column(db.DateTime)
    archive_note = db.Column(db.Text)


class CourseInsight(TimestampMixin, db.Model):
    __tablename__ = "course_insights"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    semester = db.Column(db.String(64), nullable=False)
    class_scope = db.Column(db.String(255), nullable=False, default="全部班级")
    provider = db.Column(db.String(64), nullable=False, default="智能生成")
    model_name = db.Column(db.String(128), nullable=False, default="")
    prompt_version = db.Column(db.String(64), nullable=False, default="course-insight-v1")
    overview_text = db.Column(db.Text)
    objective_analysis_json = db.Column(db.Text)
    improvement_json = db.Column(db.Text)
    raw_response_json = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint("course_id", "semester", "class_scope", name="uq_course_insight_scope"),
    )
