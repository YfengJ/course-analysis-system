# Course Analysis System

课程目标达成度报告系统。系统面向高校课程评价场景，支持课程信息维护、教学大纲解析、成绩文件导入、课程目标达成度计算、可视化分析、持续改进建议生成和 Word 报告导出。

> 公开仓库不包含任何真实课程、学生、成绩、教学大纲、数据库、导出报告、API Key 或本地缓存文件。运行后请自行上传本地数据。

## 功能概览

- 课程管理：新建课程、维护课程基本信息、课程目标和目标权重。
- 教学大纲解析：上传 `.docx` 教学大纲，提取课程基本信息、课程目标、毕业要求指标点和支撑强度。
- 成绩导入：支持 `.xls`、`.xlsx`、`.xlsm`、`.csv`，支持同一课程多个班级成绩文件合并导入。
- 达成度计算：计算分目标定量达成度、定性达成度、课程总达成度、达标人数和区间分布。
- 可视化分析：展示课程目标对比、考核项得分率、区间分布和总达成状态。
- 报告生成：预览报告并导出 Word 文档。
- 改进建议：可使用内置规则生成分析文字，也可选配兼容 OpenAI Chat Completions 风格接口的大模型服务。

## 技术栈

- 后端：Python、Flask、Flask-SQLAlchemy、Flask-WTF
- 数据库：SQLite
- 数据处理：pandas、openpyxl、xlrd
- 文档生成：python-docx、Pillow
- 前端：Jinja2、Bootstrap、ECharts

## 目录结构

```text
.
├── app.py                         # Flask 应用入口
├── config.py                      # 配置项与环境变量读取
├── forms.py                       # 表单定义
├── init_db.py                     # 初始化数据库
├── models.py                      # SQLAlchemy 数据模型
├── routes/                        # 路由层
├── services/                      # 业务服务层
│   └── template_adapters/         # 教学大纲、成绩模板、报告模板适配器
├── static/                        # CSS、JS、图标
├── templates/                     # Jinja2 页面模板
├── requirements.txt               # Python 依赖
├── .env.example                   # 环境变量示例，不包含真实密钥
└── .gitignore                     # 隐私与运行产物忽略规则
```

运行时会自动创建以下目录，这些目录不会提交到仓库：

```text
uploads/              # 用户上传的教学大纲和成绩文件
exports/              # 导出的 Word 报告和成绩模板
instance/             # SQLite 数据库
sample_data/          # 可选的本地模板或演示文件
tmp/                  # 临时图表、检查文件、缓存
```

## 快速开始

### 1. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 准备环境变量

```bash
cp .env.example .env
```

如不需要大模型生成改进建议，可以保持 `LLM_API_KEY` 为空。系统核心导入、计算和报告导出功能不依赖大模型。

### 4. 初始化数据库

```bash
python init_db.py
```

公开版初始化时只创建数据库表，不写入真实课程或成绩数据。

### 5. 启动服务

```bash
flask --app app.py:create_app run --port 5001
```

浏览器访问：

```text
http://127.0.0.1:5001
```

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `SECRET_KEY` | Flask 密钥，生产环境应自行设置 |
| `DATABASE_URL` | 数据库地址，默认使用 `instance/attainment_system.db` |
| `REPORT_TEMPLATE_DOCX` | 可选 Word 报告模板路径 |
| `LLM_API_BASE` | 可选大模型 API 地址 |
| `LLM_API_KEY` | 可选大模型 API Key，不要提交到 Git |
| `LLM_MODEL` | 可选大模型名称 |
| `LLM_TIMEOUT` | 大模型请求超时时间，单位为秒 |
| `LLM_VERIFY_SSL` | 是否校验 HTTPS 证书，默认 `true` |

## 使用流程

1. 新建课程或上传教学大纲创建课程。
2. 检查课程目标、毕业要求支撑关系和考核项权重。
3. 上传一个或多个成绩文件。
4. 进入“计算分析”页面，执行达成度计算。
5. 进入“AI 第五章”页面，生成或刷新分析与改进建议。
6. 进入“报告预览”页面，导出 Word 报告。

## 隐私说明

本仓库刻意不包含以下内容：

- 真实课程名称、课程编号、教师姓名、班级、学生信息。
- 教学大纲、成绩文件、报告 Word、论文材料。
- SQLite 数据库。
- `.env`、API Key、Token、浏览器缓存、IDE 配置。
- 上传目录、导出目录、临时目录和运行缓存。

上传真实数据前，请确保它们只保存在本地运行目录中，不要提交到公开仓库。

## License

MIT
