from models import (
    Assessment,
    Course,
    CourseObjective,
    ObjectiveAssessmentWeight,
    db,
)


DEFAULT_SEMESTER = "2025-2026学年第1学期"

GENERIC_ASSESSMENTS = [
    ("平时表现", 10, 1),
    ("过程作业", 20, 2),
    ("实践任务", 20, 3),
    ("期末考核", 50, 4),
]

GENERIC_OBJECTIVES = [
    (1, "课程目标1", "请根据课程教学大纲完善课程目标1描述。", 35),
    (2, "课程目标2", "请根据课程教学大纲完善课程目标2描述。", 30),
    (3, "课程目标3", "请根据课程教学大纲完善课程目标3描述。", 35),
]

GENERIC_WEIGHT_CONFIG = {
    "课程目标1": {"平时表现": 4, "过程作业": 8, "实践任务": 8, "期末考核": 15},
    "课程目标2": {"平时表现": 3, "过程作业": 6, "实践任务": 6, "期末考核": 15},
    "课程目标3": {"平时表现": 3, "过程作业": 6, "实践任务": 6, "期末考核": 20},
}


def get_default_course():
    """Public release has no built-in course data."""
    return Course.query.first()


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


def seed_all(base_dir):
    """初始化公开版数据库表结构，不写入任何真实课程、学生、成绩或报告数据。"""
    db.session.commit()
