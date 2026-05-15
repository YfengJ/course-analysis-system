from pathlib import Path
import re

import pandas as pd


class ScoreTemplateAdapter:
    """兼容老师 xlsm 模板与通用成绩文件的成绩表适配器。"""

    NAME = "score_template_adapter"
    REQUIRED_COLUMNS = {"学号"}
    ASSESSMENT_ALIASES = {
        "随堂": "随堂测试",
        "随堂测试": "随堂测试",
        "上机": "上机实践",
        "上机实践": "上机实践",
        "课后作业": "课后作业",
        "大作业": "大作业",
        "期末考试": "期末考试",
    }
    METADATA_LABELS = {
        "课程代码": "course_code",
        "课程编号": "course_code",
        "课程名称": "course_name",
        "课程性质": "nature",
        "学分": "credits",
        "学时": "hours",
        "考核方式": "assessment_method",
        "考核形式": "assessment_method",
        "开课学期": "semester",
        "授课对象": "class_names",
        "授课班级": "class_names",
        "上课班级": "class_names",
        "课程目标达成度期望值": "expected_value",
        "课程负责人": "course_owner",
        "任课教师": "instructors",
        "任课老师": "instructors",
    }

    @classmethod
    def load_score_payload(cls, file_path: Path, normalize_columns):
        suffix = file_path.suffix.lower()
        if suffix == ".csv":
            dataframe = normalize_columns(pd.read_csv(file_path))
            dataframe = cls._ensure_optional_columns(dataframe)
            dataframe = cls._drop_non_student_rows(dataframe)
            return {
                "mode": "flat",
                "dataframe": dataframe,
                "sheet_name": "CSV",
                "source_format": "csv",
                "mapping": cls._build_mapping(dataframe),
                "metadata": {},
            }

        sheets = pd.read_excel(file_path, sheet_name=None, header=None)
        metadata = cls._extract_workbook_metadata(sheets)
        teacher_payload = cls._find_teacher_workbook(sheets)
        if teacher_payload:
            teacher_payload["source_format"] = suffix.lstrip(".")
            teacher_payload["metadata"] = metadata
            return teacher_payload

        best_match = None
        for sheet_name, raw in sheets.items():
            candidate = cls._find_header_frame(raw, normalize_columns)
            if candidate is None:
                continue
            score_columns = [item for item in candidate.columns if item not in {"学号", "姓名", "班级"} and str(item).strip()]
            if not best_match or len(score_columns) > len(best_match["score_columns"]):
                best_match = {
                    "sheet_name": sheet_name,
                    "dataframe": candidate,
                    "score_columns": score_columns,
                }

        if not best_match:
            raise ValueError("未识别到包含课程目标成绩列的工作表，请检查上传文件格式是否与系统支持的成绩模板一致。")

        dataframe = best_match["dataframe"].copy()
        dataframe = dataframe.astype(object).where(pd.notna(dataframe), "")
        dataframe = cls._ensure_optional_columns(dataframe)
        dataframe = cls._drop_non_student_rows(dataframe)
        return {
            "mode": "flat",
            "dataframe": dataframe,
            "sheet_name": best_match["sheet_name"],
            "source_format": suffix.lstrip("."),
            "mapping": cls._build_mapping(dataframe),
            "metadata": metadata,
        }

    @classmethod
    def load_score_frame(cls, file_path: Path, normalize_columns):
        payload = cls.load_score_payload(file_path, normalize_columns)
        if payload["mode"] != "flat":
            raise ValueError("当前文件为课程目标分项成绩模板，请使用完整导入流程处理。")
        return {
            "dataframe": payload["dataframe"],
            "sheet_name": payload["sheet_name"],
            "source_format": payload["source_format"],
            "mapping": payload["mapping"],
        }

    @classmethod
    def _find_header_frame(cls, raw: pd.DataFrame, normalize_columns):
        for header_index in range(min(len(raw.index), 25)):
            header_row = [str(item).strip() for item in raw.iloc[header_index].tolist()]
            candidate = raw.iloc[header_index + 1 :].copy()
            candidate.columns = header_row
            candidate = candidate.dropna(how="all")
            candidate = normalize_columns(candidate)
            candidate = cls._ensure_optional_columns(candidate)
            candidate = cls._drop_non_student_rows(candidate)
            columns = {str(item).strip() for item in candidate.columns if str(item).strip()}
            if cls.REQUIRED_COLUMNS.issubset(columns):
                score_columns = columns - {"序号", "学号", "姓名", "班级", "学期"}
                if score_columns:
                    return candidate
        return None

    @classmethod
    def _find_teacher_workbook(cls, sheets):
        for sheet_name, raw in sheets.items():
            payload = cls._parse_teacher_sheet(sheet_name, raw)
            if payload:
                return payload
        return None

    @classmethod
    def _parse_teacher_sheet(cls, sheet_name, raw: pd.DataFrame):
        if len(raw.index) < 6:
            return None

        row3 = [cls._cell_text(item) for item in raw.iloc[2].tolist()]
        row4 = [cls._cell_text(item) for item in raw.iloc[3].tolist()]
        row5 = [cls._cell_text(item) for item in raw.iloc[4].tolist()]
        row6 = [cls._cell_text(item) for item in raw.iloc[5].tolist()]

        if "学号" not in row4 or "课程目标1" not in row3:
            return None

        objective_blocks = []
        objective_pattern = re.compile(r"课程目标\s*(\d+)")
        total_column = None
        col_index = 0
        while col_index < len(row4):
            title = row3[col_index]
            match = objective_pattern.search(title)
            if match:
                objective_label = f"课程目标{match.group(1)}"
                item_columns = []
                pointer = col_index
                while pointer < len(row4):
                    header = row4[pointer]
                    if not header:
                        pointer += 1
                        continue
                    if "达成度" in header:
                        objective_blocks.append(
                            {
                                "objective_ref": objective_label,
                                "objective_weight": cls._safe_float(row5[pointer]),
                                "attainment_column_index": pointer,
                                "items": item_columns,
                            }
                        )
                        col_index = pointer
                        break
                    item_columns.append(
                        {
                            "assessment_name": cls.ASSESSMENT_ALIASES.get(header, header),
                            "target_score": cls._safe_float(row5[pointer]),
                            "full_score": cls._safe_float(row6[pointer]),
                            "column_index": pointer,
                            "column_label": header,
                        }
                    )
                    pointer += 1
                else:
                    break
            elif "总达成度" in row4[col_index]:
                total_column = col_index
            col_index += 1

        if not objective_blocks:
            return None

        student_no_index = row4.index("学号")
        name_index = row4.index("姓名") if "姓名" in row4 else None
        class_index = row4.index("班级") if "班级" in row4 else None
        records = []
        for row_index in range(6, len(raw.index)):
            serial_no = cls._cell_text(raw.iat[row_index, 0]) if raw.shape[1] > 0 else ""
            student_no = cls._cell_text(raw.iat[row_index, student_no_index]) if student_no_index < raw.shape[1] else ""
            if serial_no in {"合计", "平均", "汇总"}:
                continue
            if student_no.lower() in {"nan", "none", "合计", "平均", "汇总"}:
                continue
            if not student_no:
                continue
            record = {
                "row_no": row_index + 1,
                "student_no": student_no,
                "name": cls._cell_text(raw.iat[row_index, name_index]) if name_index is not None and name_index < raw.shape[1] else "",
                "class_name": cls._cell_text(raw.iat[row_index, class_index]) if class_index is not None and class_index < raw.shape[1] else "",
                "objective_scores": {},
                "objective_attainment": {},
                "total_attainment": cls._safe_float(raw.iat[row_index, total_column]) if total_column is not None and total_column < raw.shape[1] else None,
            }
            for block in objective_blocks:
                item_scores = {}
                for item in block["items"]:
                    if item["column_index"] >= raw.shape[1]:
                        continue
                    item_scores[item["assessment_name"]] = cls._safe_float(raw.iat[row_index, item["column_index"]])
                record["objective_scores"][block["objective_ref"]] = item_scores
                if block["attainment_column_index"] < raw.shape[1]:
                    record["objective_attainment"][block["objective_ref"]] = cls._safe_float(raw.iat[row_index, block["attainment_column_index"]])
            records.append(record)

        mapping = {}
        for block in objective_blocks:
            mapping[block["objective_ref"]] = {
                item["column_label"]: item["assessment_name"] for item in block["items"]
            }

        return {
            "mode": "objective_split",
            "sheet_name": sheet_name,
            "records": records,
            "objective_blocks": objective_blocks,
            "mapping": mapping,
        }

    @classmethod
    def _extract_workbook_metadata(cls, sheets):
        metadata = {}
        for raw in sheets.values():
            for row_index in range(raw.shape[0]):
                for col_index in range(raw.shape[1]):
                    label = cls._normalize_metadata_label(raw.iat[row_index, col_index])
                    key = cls.METADATA_LABELS.get(label)
                    if not key or key in metadata:
                        continue
                    value = cls._find_metadata_value(raw, row_index, col_index)
                    if value in ("", None):
                        continue
                    metadata[key] = value
        if "expected_value" in metadata:
            metadata["expected_value"] = cls._normalize_expected_value(metadata["expected_value"])
        if "semester" in metadata:
            metadata["semester"] = cls._normalize_semester(metadata["semester"])
        if "hours" in metadata:
            metadata["hours"] = cls._safe_float(metadata["hours"])
        if "credits" in metadata:
            metadata["credits"] = cls._safe_float(metadata["credits"])
        return metadata

    @classmethod
    def _find_metadata_value(cls, raw: pd.DataFrame, row_index: int, col_index: int):
        current = cls._cell_text(raw.iat[row_index, col_index])
        inline_match = re.match(r"^\s*([^：:]+)\s*[:：]\s*(.+?)\s*$", current)
        if inline_match:
            return inline_match.group(2).strip()

        for offset in range(1, 5):
            target_col = col_index + offset
            if target_col >= raw.shape[1]:
                break
            value = cls._cell_text(raw.iat[row_index, target_col])
            if value:
                return value
        return ""

    @staticmethod
    def _normalize_metadata_label(value: str) -> str:
        text = str(value or "").replace("\n", "").strip()
        if "：" in text or ":" in text:
            text = re.split(r"[:：]", text, maxsplit=1)[0]
        return re.sub(r"\s+", "", text)

    @classmethod
    def _normalize_expected_value(cls, value):
        numeric_value = cls._safe_float(value)
        if numeric_value > 1:
            numeric_value = numeric_value / 100
        return round(numeric_value, 4)

    @staticmethod
    def _normalize_semester(value):
        text = str(value or "").strip()
        replacements = {
            "第一学期": "第1学期",
            "第二学期": "第2学期",
            "第三学期": "第3学期",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    @classmethod
    def _ensure_optional_columns(cls, dataframe: pd.DataFrame) -> pd.DataFrame:
        if "姓名" not in dataframe.columns:
            dataframe["姓名"] = ""
        if "班级" not in dataframe.columns:
            dataframe["班级"] = ""
        return dataframe

    @staticmethod
    def _drop_non_student_rows(dataframe: pd.DataFrame) -> pd.DataFrame:
        if "学号" not in dataframe.columns:
            return dataframe
        student_no = dataframe["学号"].astype(str).str.strip()
        invalid_pattern = r"^(?:|nan|none)$|合计|平均|人数|说明|注意|此行不动|^\["
        return dataframe[~student_no.str.contains(invalid_pattern, case=False, regex=True, na=True)].copy()

    @staticmethod
    def _build_mapping(dataframe: pd.DataFrame):
        mapping = {}
        for column in dataframe.columns:
            clean_name = str(column).strip()
            if clean_name:
                mapping[clean_name] = clean_name
        return mapping

    @staticmethod
    def _cell_text(value) -> str:
        if value is None or pd.isna(value):
            return ""
        return str(value).strip().replace("\n", " / ")

    @staticmethod
    def _safe_float(value):
        if value in (None, "") or pd.isna(value):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
