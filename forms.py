from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import FloatField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, NumberRange, Optional


class CourseForm(FlaskForm):
    code = StringField("课程编号", validators=[DataRequired(), Length(max=64)])
    name = StringField("课程名称", validators=[DataRequired(), Length(max=128)])
    english_name = StringField("英文名称", validators=[Optional(), Length(max=128)])
    course_owner = StringField("课程负责人", validators=[DataRequired(), Length(max=64)])
    semester = StringField("开课学期", validators=[Optional(), Length(max=64)])
    class_names = StringField("授课班级", validators=[Optional(), Length(max=255)])
    hours = FloatField("学时", validators=[DataRequired(), NumberRange(min=0)])
    credits = FloatField("学分", validators=[DataRequired(), NumberRange(min=0)])
    assessment_method = StringField("考核方式", validators=[Optional(), Length(max=64)])
    expected_value = FloatField("期望值", validators=[DataRequired(), NumberRange(min=0, max=1)])
    department = StringField("开课单位", validators=[Optional(), Length(max=128)])
    major = StringField("适用专业", validators=[Optional(), Length(max=128)])
    description = TextAreaField("课程简介", validators=[Optional()])
    submit = SubmitField("保存课程信息")


class CourseCreateForm(CourseForm):
    submit = SubmitField("创建课程")


class ObjectiveForm(FlaskForm):
    title = StringField("目标标题", validators=[DataRequired(), Length(max=64)])
    description = TextAreaField("目标描述", validators=[DataRequired()])
    weight = FloatField("目标权重", validators=[DataRequired(), NumberRange(min=0, max=100)])
    submit = SubmitField("保存课程目标")


class OutlineUploadForm(FlaskForm):
    file = FileField(
        "上传教学大纲",
        validators=[
            FileRequired(),
            FileAllowed(["docx"], "仅支持 docx 文件"),
        ],
    )
    submit = SubmitField("上传并解析")


class ScoreUploadForm(FlaskForm):
    semester = StringField("学期", validators=[DataRequired(), Length(max=64)])
    class_scope = StringField("班级范围", validators=[Optional(), Length(max=255)])
    file = FileField(
        "上传成绩文件（可多选）",
        validators=[
            FileRequired(),
            FileAllowed(["xls", "xlsx", "xlsm", "csv"], "仅支持 Excel 或 CSV 文件"),
        ],
    )
    submit = SubmitField("导入成绩")


class AnalysisFilterForm(FlaskForm):
    semester = SelectField("学期", choices=[], validators=[Optional()])
    class_scope = SelectField("班级", choices=[], validators=[Optional()])
    submit = SubmitField("查看分析")


class LoginForm(FlaskForm):
    username = StringField("账号", validators=[DataRequired(), Length(max=64)])
    password = PasswordField("密码", validators=[DataRequired(), Length(max=128)])
    submit = SubmitField("登录系统")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("当前密码", validators=[DataRequired(), Length(max=128)])
    new_password = PasswordField("新密码", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "确认新密码",
        validators=[
            DataRequired(),
            EqualTo("new_password", message="两次输入的新密码不一致"),
            Length(max=128),
        ],
    )
    submit = SubmitField("更新密码")
