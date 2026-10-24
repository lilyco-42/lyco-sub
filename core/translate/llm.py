"""OpenAI 兼容 LLM 翻译 —— 当前唯一可靠的路径。

要点（都是踩过坑的）：
- 必须**按句返回 JSON**，不能用自由文本，否则行数对不上会导致时间轴错位；
- 必须**批量 + 重试**，单句请求会被限流；
- 返回条数不符时要能对齐（补齐/截断），而不是静默错位。
"""

from __future__ import annotations

import json
import time

import httpx

from ..config import Settings
from .base import TranslateError, Translator, register

FENCE = "```"

SYSTEM_PROMPT = (
    "You are a professional subtitle translator. "
    "Translate each numbered subtitle line into {target}. "
    "Rules: keep the meaning, keep it concise enough to read on screen, "
    "never merge or split lines, never add explanations. "
    'Return ONLY a JSON object: {"lines": ["...", "..."]} with exactly the same number of items.'
)


class LLMTranslator(Translator):
    name = "llm"
    label = "LLM 翻译（OpenAI 兼容 / 唯一可靠路径）"
    needs_key = True
    notes = "免费必应/谷歌通道已失效（404/429），只能用 LLM。支持任意 OpenAI 兼容端点。"

    def __init__(self, settings: Settings):
        self.settings = settings

    def available(self) -> tuple[bool, str]:
        if not self.settings.llm_api_key:
            return False, "未配置 LLM API Key（LYCOSUB_LLM_API_KEY 或 OPENAI_API_KEY）"
        return True, ""

    def _chat(self, client: httpx.Client, payload_lines: list[str], target: str) -> list[str]:
        body = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT.format(target=target)},
                {"role": "user", "content": json.dumps({"lines": payload_lines}, ensure_ascii=False)},
            ],
        }
        r = client.post(
            f"{self.settings.llm_api_base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            json=body,
            timeout=120,
        )
        if r.status_code >= 400:
            raise TranslateError(f"LLM 返回 {r.status_code}: {r.text[:300]}")
        content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        if content.startswith(FENCE):
            content = content[len(FENCE):]
            if content.lstrip().startswith("json"):
                content = content.lstrip()[4:]
            content = content.rsplit(FENCE, 1)[0]
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise TranslateError(f"LLM 返回非 JSON: {content[:200]}") from exc
        out = data.get("lines") if isinstance(data, dict) else data
        if not isinstance(out, list):
            raise TranslateError(f"LLM 返回结构异常: {str(data)[:200]}")
        return [str(x) for x in out]

    def translate_batch(self, texts: list[str], target: str, source: str | None = None) -> list[str]:
        ok, reason = self.available()
        if not ok:
            raise TranslateError(reason)

        batch_size = 20
        results: list[str] = []
        with httpx.Client() as client:
            for i in range(0, len(texts), batch_size):
                chunk = texts[i:i + batch_size]
                last_err: Exception | None = None
                for attempt in range(3):
                    try:
                        got = self._chat(client, chunk, target)
                        if len(got) < len(chunk):
                            got = got + chunk[len(got):]
                        results.extend(got[:len(chunk)])
                        last_err = None
                        break
                    except TranslateError as exc:
                        last_err = exc
                        time.sleep(1.5 * (attempt + 1))
                if last_err is not None:
                    raise last_err
        return results


def build(settings: Settings) -> LLMTranslator:
    return register(LLMTranslator(settings))
