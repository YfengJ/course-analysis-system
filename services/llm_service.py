import json
import re
import ssl
from urllib import error, parse, request

from flask import current_app

try:
    import certifi
except ImportError:  # pragma: no cover - optional dependency
    certifi = None


class LLMService:
    """调用可选的大模型接口，用于生成更自然的改进建议。"""

    COURSE_INSIGHT_MAX_RETRIES = 2

    @staticmethod
    def is_configured() -> bool:
        return bool(current_app.config.get("LLM_API_KEY") and current_app.config.get("LLM_MODEL"))

    @staticmethod
    def _ssl_context():
        if not current_app.config.get("LLM_VERIFY_SSL", True):
            return ssl._create_unverified_context()
        if certifi:
            return ssl.create_default_context(cafile=certifi.where())
        return ssl.create_default_context()

    @classmethod
    def build_course_insight(cls, prompt: str):
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一名高校课程达成度评价与持续改进专家。"
                    "你必须严格依据给定课程数据、教学大纲和课程目标生成结果，"
                    "不要编造不存在的教学安排或统计结论。"
                    "输出必须是合法、完整、可直接解析的 JSON 对象。"
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        last_error = None
        last_content = ""
        for _ in range(cls.COURSE_INSIGHT_MAX_RETRIES):
            content = cls._chat(
                messages,
                temperature=0.25,
                max_tokens=2600,
                json_mode=True,
            )
            last_content = content
            try:
                return cls._parse_json_object(content)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc

        raise ValueError(
            "模型连续返回了无法解析的 JSON 内容。"
            f"最后一次错误：{last_error}。"
            f"响应片段：{cls._safe_excerpt(last_content)}"
        ) from last_error

    @classmethod
    def build_improvement_actions(cls, summary, fallback_actions):
        if not cls.is_configured():
            return {
                "items": fallback_actions,
                "source": "rule",
            }

        prompt = cls._build_prompt(summary, fallback_actions)
        try:
            content = cls._chat(
                [
                    {
                        "role": "system",
                        "content": "你是一名高校课程教学改进专家，请根据课程达成度结果输出自然、具体、避免套话的中文改进建议。",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.8,
                max_tokens=700,
            )
            actions = cls._parse_actions(content)
            if actions:
                return {
                    "items": actions[:3],
                    "source": "llm",
                }
        except Exception:
            pass

        return {
            "items": fallback_actions,
            "source": "rule",
        }

    @classmethod
    def _chat(
        cls,
        messages,
        temperature: float = 0.8,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        base = current_app.config["LLM_API_BASE"].rstrip("/")
        url = f"{base}/chat/completions"
        payload = {
            "model": current_app.config["LLM_MODEL"],
            "temperature": temperature,
            "messages": messages,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {current_app.config['LLM_API_KEY']}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=current_app.config["LLM_TIMEOUT"], context=cls._ssl_context()) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_json_object(content: str):
        content = (content or "").strip()
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        repaired = LLMService._repair_known_json_issues(content)
        if repaired is not None:
            return repaired

        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            candidate = match.group(0)
            repaired = LLMService._repair_known_json_issues(candidate)
            if repaired is not None:
                return repaired
            return json.loads(candidate)
        raise ValueError("模型未返回可解析的 JSON 对象")

    @staticmethod
    def _repair_known_json_issues(content: str):
        stripped = (content or "").strip()
        if not stripped:
            return None

        fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
        candidate = re.sub(r",(\s*[}\]])", r"\1", fenced)
        if candidate != stripped:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        key = '"improvement_actions"'
        if content.count(key) > 1:
            first = content.find(key)
            last = content.rfind(key)
            candidate = content[:first] + content[last:]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        return None

    @classmethod
    def _repair_json_object_with_model(cls, content: str):
        repaired_content = cls._chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是一名 JSON 修复助手。"
                        "你只能输出一个合法、完整、可直接解析的 JSON 对象。"
                        "不得补充解释，不得使用 Markdown。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "下面是一个本应为 JSON 对象的文本，但它格式有误。"
                        "请尽量保留原有内容与字段结构，只修复为合法 JSON：\n"
                        f"{content}"
                    ),
                },
            ],
            temperature=0,
            max_tokens=1800,
            json_mode=True,
        )
        return cls._parse_json_object(repaired_content)

    @staticmethod
    def _build_prompt(summary, fallback_actions):
        objective_lines = []
        for item in summary["objective_results"]:
            objective_lines.append(
                f"{item['objective_title']}：定量达成度{item['quantitative_attainment']:.2f}，"
                f"定性达成度{item['qualitative_attainment']:.2f}，"
                f"薄弱环节为"
                f"{min(item['assessment_details'], key=lambda detail: detail['score_rate'])['assessment_name'] if item['assessment_details'] else '无'}。"
            )
        return "\n".join(
            [
                f"课程总定量达成度：{summary['total_quantitative_attainment']:.2f}",
                f"课程总定性达成度：{summary['total_qualitative_attainment']:.2f}",
                "分目标情况：",
                *objective_lines,
                "请输出 3 条更自然、更有针对性的持续改进建议。",
                "每条建议控制在 50-90 字，避免重复句式，不要使用“针对课程目标X，建议”这种完全相同的开头。",
                "请仅返回 JSON 数组字符串，例如：[\"建议1\", \"建议2\", \"建议3\"]",
                f"如需参考，可基于以下已有建议重写：{json.dumps(fallback_actions, ensure_ascii=False)}",
            ]
        )

    @staticmethod
    def _parse_actions(content: str):
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except json.JSONDecodeError:
            pass

        lines = []
        for raw_line in content.splitlines():
            line = raw_line.strip().lstrip("-").lstrip("•").strip()
            if line:
                lines.append(line)
        return lines

    @staticmethod
    def _safe_excerpt(content: str, limit: int = 240):
        snippet = re.sub(r"\s+", " ", (content or "")).strip()
        if len(snippet) <= limit:
            return snippet
        return snippet[:limit] + "..."
