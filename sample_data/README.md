# 示例数据说明

本目录提供系统演示所需的示例数据：

- `sample_scores.csv`：标准成绩导入模板，可直接在“成绩导入”页面上传。
- `sample_column_mapping.json`：列名映射说明，便于展示系统的兼容导入能力。
- `sample_course_config.json`：默认课程模板数据摘要。

使用 `python init_db.py --reset-demo` 后，数据库会写入一套“示例课程”演示数据，包含课程目标、考核项和 168 名脱敏学生成绩记录。
