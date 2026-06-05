# 课程目标达成度报告系统

中文 | [English](README.en.md)

这是一个面向课程目标达成度分析、报告生成和证据归档的本地化 Web 系统。系统把教学大纲、课程目标、考核项权重、学生成绩、计算分析、报告版本和归档材料串成一条可追溯的数据链，适合用于课程评价、持续改进和日常教学资料整理。

## 界面预览

![课程工作台](docs/images/dashboard.png)

![达成度分析](docs/images/analysis.png)

![报告预览](docs/images/report-preview.png)

## 主要功能

- 课程管理：维护课程基本信息、课程目标、毕业要求指标点和考核项权重。
- 教学大纲解析：从 `.docx` 教学大纲中提取课程信息、目标描述、毕业要求映射和考核支撑关系。
- 成绩导入预检：支持 `.xls/.xlsx/.xlsm/.csv`，可一次选择多个班级文件；系统先预检学生数、班级、工作表、列映射和分值异常，确认后才写入数据库。
- 达成度分析：计算课程目标定量达成度、定性达成度、统计特征、达标人数、区间分布和课程总达成度。
- 人工修订：可在计算分析页调整定性评价计数和说明，修订内容会同步进入报告。
- 第五章编辑：可使用智能建议生成评价与改进措施，也可手工编辑后保存到报告。
- 报告导出与归档：支持报告预览、Word 导出、版本记录、最终版归档和相邻版本对比。
- 报告质量检查：在正式导出或归档前检查课程负责人、课程目标、成绩数据、第四章计算、第五章内容和报告归档状态。
- 课程归档包：一键导出课程证据包，包含分析摘要、质量检查结果、教学大纲解析、导入日志、分析快照和已生成 Word 报告。
- 数据备份与恢复：在“数据维护”页面创建系统备份包，备份数据库、上传文件和报告文件；恢复前会自动保存当前数据库副本。

## 典型使用顺序

1. 新建课程，填写课程基本信息。
2. 上传教学大纲，检查系统解析出的课程目标、指标点和考核支撑关系。
3. 上传一个或多个班级成绩文件，完成导入预检并确认写入。
4. 在计算分析页执行达成度计算，必要时进行人工修订。
5. 编辑第五章评价与持续改进内容。
6. 查看报告预览，运行报告质量检查。
7. 导出 Word 报告，并根据需要归档最终版或下载课程归档包。

## 技术栈

- 后端：Python、Flask、SQLAlchemy、WTForms
- 前端：Jinja2、Bootstrap 5、ECharts、Mermaid
- 数据处理：pandas、openpyxl
- 文档导出：python-docx
- 数据库：SQLite

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python init_db.py
python app.py
```

访问：`http://127.0.0.1:5000`

首次启动会自动创建管理员账号，默认账号为 `admin`，默认密码为 `admin123`。系统会要求先修改初始密码，修改完成后才能进入课程数据页面。正式使用时建议通过环境变量设置初始账号和随机强密码。

`python init_db.py` 默认只创建表结构，不会删除现有数据库，也不会写入样例课程。

如需重置本地 SQLite 并写入内置脱敏样例数据：

```bash
python init_db.py --reset-demo
```

执行重置时，脚本会先把旧数据库备份为 `.bak` 文件。

## 可选环境变量

智能建议功能是可选的。未配置模型密钥时，建课、导入、计算、手工编辑和报告导出都可以正常使用。

```bash
export SECRET_KEY="请替换为本机随机字符串"
export COURSE_SYSTEM_DATA_DIR="/Users/你的用户名/course-system-data"
export DEFAULT_ADMIN_USERNAME="admin"
export DEFAULT_ADMIN_PASSWORD="请替换为临时强密码"
export LLM_API_BASE="https://api.deepseek.com"
export LLM_API_KEY="你的模型服务密钥"
export LLM_MODEL="deepseek-v4-flash"
export LLM_TIMEOUT="45"
```

`LLM_TIMEOUT` 的单位是秒。

## 数据与隐私

本仓库只应提交源代码、模板和脱敏样例。以下内容默认被 `.gitignore` 和发布包脚本排除：

- `.env`、API Key、数据库文件和备份文件
- `instance/`、`uploads/`、`exports/`、`datasoruce/`、`tmp/`、`output/`
- 真实课程教学大纲、成绩表、学生信息和导出的报告
- 本地虚拟环境、浏览器二进制、IDE 配置和缓存

部署使用时，建议设置 `COURSE_SYSTEM_DATA_DIR`，让数据库、上传文件、报告和备份都放在源码目录之外。新安装环境未设置该变量时，系统会优先使用 `var/` 作为运行数据目录；如果检测到旧版 `instance/attainment_system.db` 已存在，则保持旧目录兼容，避免升级后看不到原有课程。

## 发布包

生成不含真实课程数据的系统发布包：

```bash
python scripts/build_release.py
```

发布包默认写入 `dist/course-system-release.zip`，会自动排除数据库、上传文件、导出报告、真实成绩和教学大纲、本地辅助脚本、本地缓存等内容。

## 测试

```bash
python scripts/run_tests.py
```

如果本机保留了课程测试文件，也可以运行：

```bash
python -m unittest tests/test_algorithm_outline_and_multi_import.py
```

## 目录结构

```text
coursesystem/
├── app.py
├── config.py
├── forms.py
├── init_db.py
├── models.py
├── routes/
├── services/
├── static/
├── templates/
├── sample_data/
├── docs/
├── tests/
└── README.md
```

运行时目录如 `uploads/`、`exports/`、`instance/` 会由系统自动创建；设置 `COURSE_SYSTEM_DATA_DIR` 后，这些目录会迁移到指定数据目录下。

## 更多文档

- [部署与使用说明](docs/部署与使用说明.md)
- [示例数据说明](sample_data/README.md)
