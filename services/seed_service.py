import json
from pathlib import Path

from models import (
    Assessment,
    Course,
    CourseObjective,
    GraduationRequirement,
    ImportBatch,
    ObjectiveAssessmentWeight,
    ObjectiveRequirementMap,
    Score,
    Student,
    TeachingOutline,
    db,
)


DEFAULT_COURSE_CODE = "110842105"
DEFAULT_SEMESTER = "2025-2026学年第1学期"
GENERIC_ASSESSMENTS = [
    ("课后作业", 5, 1),
    ("大作业", 5, 2),
    ("随堂测试", 10, 3),
    ("期末考试", 70, 4),
    ("上机实践", 10, 5),
]
GENERIC_OBJECTIVES = [
    (1, "课程目标1", "请根据课程教学大纲完善课程目标1描述。", 35),
    (2, "课程目标2", "请根据课程教学大纲完善课程目标2描述。", 25),
    (3, "课程目标3", "请根据课程教学大纲完善课程目标3描述。", 40),
]
GENERIC_WEIGHT_CONFIG = {
    "课程目标1": {"课后作业": 5, "大作业": 5, "随堂测试": 5, "期末考试": 15, "上机实践": 5},
    "课程目标2": {"随堂测试": 5, "期末考试": 20},
    "课程目标3": {"期末考试": 35, "上机实践": 5},
}


def get_default_course():
    return Course.query.filter_by(code=DEFAULT_COURSE_CODE).first()


def get_course_or_none(course_id: int):
    return Course.query.get(course_id)


def create_generic_course_structure(course: Course):
    """为新建课程写入通用考核体系和默认课程目标骨架。"""
    if course.assessments or course.objectives:
        return course

    objective_models = []
    for sequence, title, description, weight in GENERIC_OBJECTIVES:
        model = CourseObjective(
            course_id=course.id,
            sequence=sequence,
            title=title,
            description=description,
            weight=weight,
        )
        db.session.add(model)
        objective_models.append(model)
    db.session.flush()

    assessment_models = {}
    for name, total_score, sequence in GENERIC_ASSESSMENTS:
        model = Assessment(
            course_id=course.id,
            name=name,
            total_score=total_score,
            sequence=sequence,
            description=f"{name}成绩",
        )
        db.session.add(model)
        assessment_models[name] = model
    db.session.flush()

    for objective in objective_models:
        for assessment_name, weight_score in GENERIC_WEIGHT_CONFIG[objective.title].items():
            db.session.add(
                ObjectiveAssessmentWeight(
                    objective_id=objective.id,
                    assessment_id=assessment_models[assessment_name].id,
                    weight_score=weight_score,
                )
            )

    db.session.flush()
    return course


def create_default_course():
    course = get_default_course()
    if course:
        return course

    course = Course(
        code=DEFAULT_COURSE_CODE,
        name="示例课程",
        english_name="Sample Course",
        nature="必修",
        category="专业核心课",
        hours=32,
        credits=1.5,
        assessment_method="考查",
        semester=DEFAULT_SEMESTER,
        department="计算机科学与技术系",
        major="示例专业",
        course_owner="示例教师",
        instructors="示例教师A、示例教师B",
        prerequisites="程序设计基础、数据结构、数据库基础",
        textbook="示例教材",
        reference_books="[1] 示例参考书一\n[2] 示例参考书二",
        description="通过对示例课程相关知识的介绍，使学生掌握课程核心概念、基本原理和实践方法，能够利用所学知识解决课程相关问题。",
        expected_value=0.65,
        class_names="示例2301、示例2302、示例2303、示例2304班",
        student_count=168,
        template_name="内置示例模板",
        template_source="系统内置脱敏示例",
        template_version="v2",
    )
    db.session.add(course)
    db.session.flush()

    objectives = [
        (
            1,
            "课程目标1",
            "能够理解课程核心概念和基本操作流程，针对学习与实践过程中的问题提出合理解决方案。",
            35,
        ),
        (
            2,
            "课程目标2",
            "能够将课程中的基本原理、模型方法和系统思路用于分析并解决典型应用问题。",
            25,
        ),
        (
            3,
            "课程目标3",
            "能够完成课程相关实践任务，具备需求分析、方案设计、实现验证和结果评价的能力。",
            40,
        ),
    ]
    objective_models = []
    for sequence, title, description, weight in objectives:
        model = CourseObjective(
            course_id=course.id,
            sequence=sequence,
            title=title,
            description=description,
            weight=weight,
        )
        db.session.add(model)
        objective_models.append(model)
    db.session.flush()

    requirements = [
        (
            "3",
            "设计/开发解决方案",
            "3-1",
            "能够针对行业应用需求和数据特点，选择适合的数据采集、存储及分析方案，了解影响其设计目标和技术方案的各种因素。",
            "H",
        ),
        (
            "4",
            "工程研究",
            "4-2",
            "能够依据问题特点，选择研究路线，设计实验方案。",
            "M",
        ),
        (
            "5",
            "使用现代工具",
            "5-2",
            "能够选择与使用恰当的技术、资源、现代工具和信息技术工具，对复杂数据工程问题进行分析、设计、开发、测试和验证。",
            "H",
        ),
    ]
    requirement_models = []
    for code, title, indicator_point, description, _ in requirements:
        model = GraduationRequirement(
            code=code,
            title=title,
            indicator_point=indicator_point,
            description=description,
        )
        db.session.add(model)
        requirement_models.append(model)
    db.session.flush()

    for objective, requirement, strength in zip(
        objective_models,
        requirement_models,
        [item[4] for item in requirements],
    ):
        db.session.add(
            ObjectiveRequirementMap(
                objective_id=objective.id,
                requirement_id=requirement.id,
                support_strength=strength,
            )
        )

    assessment_models = {}
    for name, total_score, sequence in GENERIC_ASSESSMENTS:
        model = Assessment(
            course_id=course.id,
            name=name,
            total_score=total_score,
            sequence=sequence,
            description=f"{name}成绩",
        )
        db.session.add(model)
        assessment_models[name] = model
    db.session.flush()

    for objective in objective_models:
        for assessment_name, weight_score in GENERIC_WEIGHT_CONFIG[objective.title].items():
            db.session.add(
                ObjectiveAssessmentWeight(
                    objective_id=objective.id,
                    assessment_id=assessment_models[assessment_name].id,
                    weight_score=weight_score,
                )
            )

    outline_payload = {
        "course_name": course.name,
        "course_code": course.code,
        "hours_credits": f"{course.hours}/{course.credits}",
        "assessment_method": course.assessment_method,
        "objectives": [{"title": item.title, "description": item.description} for item in objective_models],
        "requirements": [
            {
                "indicator_point": req.indicator_point,
                "title": req.title,
                "description": req.description,
            }
            for req in requirement_models
        ],
    }
    db.session.add(
        TeachingOutline(
            course_id=course.id,
            filename="系统内置教学大纲",
            raw_text="系统根据默认课程模板预置的教学大纲摘要。",
            parsed_json=json.dumps(outline_payload, ensure_ascii=False, indent=2),
            summary="包含课程基本信息、课程目标、毕业要求指标点及教学内容摘要。",
            parser_name="seed_service",
            parse_status="已解析",
            confidence=0.95,
            source_template="系统内置示例模板",
        )
    )

    return course


def _student_name(index: int) -> str:
    return f"学生{index:03d}"


def _build_sample_score(index: int, total_score: float, offset: int) -> float:
    base_rate = 0.73 + ((index * 7 + offset) % 18) / 100
    if index % 11 == 0:
        base_rate -= 0.08
    if index % 17 == 0:
        base_rate += 0.05
    rate = max(0.48, min(0.96, base_rate))
    return round(total_score * rate, 1)


def create_sample_students_and_scores(course: Course):
    if Student.query.filter_by(course_id=course.id).count() > 0:
        return

    assessments = {item.name: item for item in course.assessments}
    classes = ["2301班", "2302班", "2303班", "2304班"]

    for index in range(1, 169):
        student = Student(
            course_id=course.id,
            student_no=f"2023{index:04d}",
            name=_student_name(index),
            class_name=classes[(index - 1) // 42],
            semester=course.semester,
            major=course.major,
        )
        db.session.add(student)
        db.session.flush()

        score_values = {
            "课后作业": _build_sample_score(index, assessments["课后作业"].total_score, 1),
            "大作业": _build_sample_score(index, assessments["大作业"].total_score, 2),
            "随堂测试": _build_sample_score(index, assessments["随堂测试"].total_score, 3),
            "期末考试": _build_sample_score(index, assessments["期末考试"].total_score, 4),
            "上机实践": _build_sample_score(index, assessments["上机实践"].total_score, 5),
        }
        for assessment_name, value in score_values.items():
            db.session.add(
                Score(
                    student_id=student.id,
                    assessment_id=assessments[assessment_name].id,
                    score=value,
                    original_column=assessment_name,
                )
            )


def create_sample_import_batch(course: Course):
    if ImportBatch.query.filter_by(course_id=course.id).first():
        return

    db.session.add(
        ImportBatch(
            course_id=course.id,
            semester=course.semester,
            class_scope="全部班级",
            filename="sample_scores.csv",
            source_format="csv",
            source_sheet="CSV",
            imported_count=168,
            issue_count=0,
            issues_json="[]",
            column_mapping_json=json.dumps(
                {
                    "学号": "学号",
                    "姓名": "姓名",
                    "班级": "班级",
                    "课后作业": "课后作业",
                    "大作业": "大作业",
                    "随堂测试": "随堂测试",
                    "期末考试": "期末考试",
                    "上机实践": "上机实践",
                },
                ensure_ascii=False,
            ),
            template_name="score_template_adapter",
            source_template="系统内置示例成绩模板",
        )
    )


def export_sample_csv(base_dir: Path):
    sample_dir = base_dir / "sample_data"
    sample_dir.mkdir(parents=True, exist_ok=True)
    path = sample_dir / "sample_scores.csv"
    if path.exists():
        return

    headers = ["学号", "姓名", "班级", "学期", "课后作业", "大作业", "随堂测试", "期末考试", "上机实践"]
    lines = [",".join(headers)]
    for index in range(1, 31):
        class_name = ["2301班", "2302班", "2303班", "2304班"][(index - 1) // 8]
        row = [
            f"2023{index:04d}",
            _student_name(index),
            class_name,
            DEFAULT_SEMESTER,
            str(_build_sample_score(index, 5, 1)),
            str(_build_sample_score(index, 5, 2)),
            str(_build_sample_score(index, 10, 3)),
            str(_build_sample_score(index, 70, 4)),
            str(_build_sample_score(index, 10, 5)),
        ]
        lines.append(",".join(row))
    path.write_text("\n".join(lines), encoding="utf-8")


def seed_all(base_dir: Path):
    """初始化数据库默认数据，并导出内置样例成绩文件。"""
    course = create_default_course()
    db.session.flush()
    create_sample_students_and_scores(course)
    create_sample_import_batch(course)
    db.session.commit()
    export_sample_csv(base_dir)
