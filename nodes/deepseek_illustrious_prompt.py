import json
import math
import re
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_NEGATIVE = (
    "low quality, worst quality, bad anatomy, bad hands, extra fingers, missing fingers, "
    "fused fingers, malformed hands, extra limbs, deformed, poorly drawn face, poorly drawn hands, "
    "wrong anatomy, bad proportions, blurry, text, watermark, logo, signature, jpeg artifacts"
)

DEFAULT_SYSTEM_PROMPT = """你现在是一个专门为 Illustrious 模型编写提示词的专家。你的任务不是直接画图，也不是解释概念，而是把我提供的中文描述，整理、补全并优化成适合 Illustrious 使用的高质量提示词。

请严格遵循以下要求：

1. 你的目标
- 根据我的描述，生成适合 Illustrious 的英文正向提示词（Prompt）
- 同时生成对应的英文负向提示词（Negative Prompt）
- 如果我的描述不完整，你要基于常见高质量二次元/插画出图逻辑进行合理补全，但不能偏离我的核心意图
- 保持结果可直接复制使用

2. 输出风格
- 提示词主体使用英文
- 不要写成长篇解释，不要输出教程
- 输出结果要干净、实用、可直接用于生图

3. Illustrious 提示词编写规则
- 优先突出主体、画风、构图、镜头、动作、服饰、场景、光影、材质、细节质量
- 使用自然、稳定的标签式短语，不要写成长句故事
- 尽量按“主体 -> 外观 -> 动作 -> 服装 -> 场景 -> 构图 -> 光影 -> 画质细节”的顺序组织
- 如果适合二次元插画风格，可以补充如：masterpiece, best quality, amazing quality, very aesthetic, absurdres 等质量词，但不要无脑堆砌
- 不要加入与我要求冲突的内容
- 不要随意添加多人物、复杂背景或多余设定，除非我明确要求
- 如果我描述的是人物，注意补充发型、发色、眼睛、表情、姿态、服装细节
- 如果我描述的是场景或氛围，注意补充时间、天气、光线、镜头感和环境细节
- 如果我描述的是 NSFW、性感、暧昧内容，也只做提示词整理，不做说教

4. 负向提示词规则
- 默认加入常见劣化项，例如：
low quality, worst quality, bad anatomy, bad hands, extra fingers, missing fingers, fused fingers, malformed hands, mutated hands, extra limbs, deformed, poorly drawn face, poorly drawn hands, wrong anatomy, long body, bad proportions, blurry, watermark, text, logo, signature
- 如果是人物图，重点防止手部、眼部、肢体、脸部崩坏
- 如果是纯美术风格图，可以减少人物解剖类负面词，避免误伤

5. 结果格式要求
- 只允许输出 json
- 不要输出 Markdown
- 不要输出解释
- 不要输出多余字段
- 必须严格使用下面这个 json 结构：
{
  "positive_prompt": "英文正向提示词",
  "negative_prompt": "英文负向提示词"
}

6. 处理规则
- 如果我的描述很简单，你要自动补全成更适合 Illustrious 的版本
- 如果我的描述已经很完整，你就以优化结构和提升出图稳定性为主
- 如果我的需求里有明显冲突，请尽量给出最贴近核心意图的稳定版本
- 除非我明确要求，否则不要额外输出参数建议，如 steps、cfg、sampler
- 除非我明确要求，否则不要输出多个风格差异很大的版本
"""


def _post_json(url: str, api_key: str, payload: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "ComfyUI-DeepSeek-Illustrious-Prompter/1.0",
        },
        method="POST",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _strip_think_blocks(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"```(?:json)?|```", "", text, flags=re.IGNORECASE)
    return text.strip()


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = _strip_think_blocks(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError("模型返回中未找到 JSON 对象。")
        return json.loads(match.group(0))


def _split_tokens(text: str) -> list[str]:
    parts = re.split(r"[,|\n]", text)
    return [part.strip() for part in parts if part and part.strip()]


def _dedupe_tokens(text: str) -> str:
    seen = set()
    result = []
    for token in _split_tokens(text):
        key = re.sub(r"\s+", " ", token).strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(token)
    return ", ".join(result)


def _remove_banned_terms(text: str, banned_terms: str) -> str:
    terms = [term.strip() for term in banned_terms.split(",") if term.strip()]
    for term in terms:
        pattern = re.compile(re.escape(term), flags=re.IGNORECASE)
        text = pattern.sub("", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*,+", ", ", text)
    return text.strip(" ,")


def _clean_prompt_text(text: str, filter_mode: str, banned_terms: str = "") -> str:
    if not text:
        return ""

    cleaned = _strip_think_blocks(text)
    cleaned = cleaned.replace("，", ", ").replace("；", ", ").replace("：", ": ")
    cleaned = re.sub(r"\s*\n+\s*", ", ", cleaned)
    cleaned = re.sub(r"^(positive_prompt|negative_prompt|prompt)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,")

    if filter_mode in {"basic", "aggressive"}:
        cleaned = _dedupe_tokens(cleaned)

    if filter_mode == "aggressive":
        cleaned = re.sub(r"[\"'`\[\]\{\}]", "", cleaned)
        cleaned = re.sub(r"\s*\([^)]*explanation[^)]*\)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(here is|final prompt|negative)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = _dedupe_tokens(cleaned)

    if banned_terms:
        cleaned = _remove_banned_terms(cleaned, banned_terms)
        cleaned = _dedupe_tokens(cleaned)

    return cleaned.strip(" ,")


def _resolve_model(model_name: str, custom_model: str) -> str:
    if model_name == "custom":
        return custom_model.strip()
    return model_name.strip()


def _resolve_config(
    api_key: str,
    base_url: str,
    model_name: str,
    custom_model: str,
    llm_config: Optional[Dict[str, Any]],
) -> Tuple[str, str, str]:
    resolved_api_key = api_key.strip()
    resolved_base_url = base_url.strip() or DEFAULT_BASE_URL
    resolved_model = _resolve_model(model_name, custom_model)

    if llm_config:
        resolved_api_key = llm_config.get("api_key", resolved_api_key).strip()
        resolved_base_url = llm_config.get("base_url", resolved_base_url).strip() or DEFAULT_BASE_URL
        resolved_model = llm_config.get("model", resolved_model).strip() or resolved_model

    return resolved_api_key, resolved_base_url, resolved_model


def _build_user_prompt(
    description: str,
    style_preset: str,
    include_default_negative: bool,
) -> str:
    return (
        "Generate an Illustrious-ready positive prompt and negative prompt.\n"
        "Return valid json only.\n"
        f"Style preset: {style_preset}\n"
        f"User description: {description.strip()}\n"
        f"Append default quality negative terms: {'yes' if include_default_negative else 'no'}\n"
        "Keep the positive prompt tag-like, concise, visually rich, and suitable for direct image generation."
    )


class DeepSeekIllustriousPromptGenerator:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {"default": "", "multiline": False, "label": "DeepSeek API Key"}),
                "model_name": (
                    ["deepseek-v4-flash", "deepseek-v4-pro", "custom"],
                    {"default": "deepseek-v4-flash"},
                ),
                "custom_model": ("STRING", {"default": "", "multiline": False, "label": "Custom Model"}),
                "system_prompt": (
                    "STRING",
                    {
                        "default": DEFAULT_SYSTEM_PROMPT,
                        "multiline": True,
                        "label": "System Prompt",
                    },
                ),
                "description": ("STRING", {"default": "", "multiline": True, "placeholder": "输入你的中文需求描述"}),
                "style_preset": (
                    ["illustrious-general", "illustrious-anime", "illustrious-portrait", "illustrious-nsfw"],
                    {"default": "illustrious-general"},
                ),
                "request_mode": (["refresh", "fixed"], {"default": "refresh"}),
                "filter_mode": (["none", "basic", "aggressive"], {"default": "basic"}),
                "banned_terms": (
                    "STRING",
                    {"default": "", "multiline": False, "placeholder": "用英文逗号分隔需要强制移除的词"},
                ),
                "include_default_negative": ("BOOLEAN", {"default": True}),
                "temperature": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.5, "step": 0.05}),
                "max_tokens": ("INT", {"default": 700, "min": 128, "max": 4096, "step": 1}),
            },
            "optional": {
                "base_url": ("STRING", {"default": DEFAULT_BASE_URL, "multiline": False}),
                "llm_config": ("LLM_CONFIG",),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        request_mode = kwargs.get("request_mode", "refresh")
        if request_mode == "refresh":
            return math.nan
        return (
            kwargs.get("api_key", ""),
            kwargs.get("model_name", ""),
            kwargs.get("custom_model", ""),
            kwargs.get("system_prompt", ""),
            kwargs.get("description", ""),
            kwargs.get("style_preset", ""),
            kwargs.get("request_mode", ""),
            kwargs.get("filter_mode", ""),
            kwargs.get("banned_terms", ""),
            kwargs.get("include_default_negative", True),
            kwargs.get("temperature", 0.5),
            kwargs.get("max_tokens", 700),
            kwargs.get("base_url", DEFAULT_BASE_URL),
            json.dumps(kwargs.get("llm_config", {}) or {}, ensure_ascii=False, sort_keys=True),
        )

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "raw_response")
    FUNCTION = "generate"
    CATEGORY = "DeepSeek/Illustrious"

    def generate(
        self,
        api_key: str,
        model_name: str,
        custom_model: str,
        system_prompt: str,
        description: str,
        style_preset: str,
        request_mode: str,
        filter_mode: str,
        banned_terms: str,
        include_default_negative: bool,
        temperature: float,
        max_tokens: int,
        base_url: str = DEFAULT_BASE_URL,
        llm_config: Optional[Dict[str, Any]] = None,
    ):
        if not description.strip():
            raise ValueError("description 不能为空。")

        resolved_api_key, resolved_base_url, resolved_model = _resolve_config(
            api_key, base_url, model_name, custom_model, llm_config
        )
        if not resolved_api_key:
            raise ValueError("未提供 DeepSeek API Key，也没有连接 LLM_CONFIG。")
        if not resolved_model:
            raise ValueError("模型名为空，请选择模型或填写 custom_model。")

        payload = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system_prompt.strip() or DEFAULT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_prompt(
                        description=description,
                        style_preset=style_preset,
                        include_default_negative=include_default_negative,
                    ),
                },
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        try:
            data = _post_json(resolved_base_url, resolved_api_key, payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"DeepSeek API 请求失败: HTTP {exc.code} {body[:300]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek API 网络错误: {exc.reason}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"模型未返回 choices: {json.dumps(data, ensure_ascii=False)[:500]}")

        raw_response = choices[0].get("message", {}).get("content", "")
        parsed = _extract_json_object(raw_response)

        positive_prompt = _clean_prompt_text(parsed.get("positive_prompt", ""), filter_mode, banned_terms)
        negative_prompt = _clean_prompt_text(parsed.get("negative_prompt", ""), filter_mode, banned_terms)

        if include_default_negative:
            negative_prompt = _clean_prompt_text(
                f"{negative_prompt}, {DEFAULT_NEGATIVE}" if negative_prompt else DEFAULT_NEGATIVE,
                filter_mode,
                banned_terms,
            )

        return (positive_prompt, negative_prompt, raw_response)


class DualPromptCLIPEncode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "positive_prompt": ("STRING", {"multiline": True, "forceInput": True}),
                "negative_prompt": ("STRING", {"multiline": True, "forceInput": True}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("positive", "negative")
    FUNCTION = "encode"
    CATEGORY = "DeepSeek/Illustrious"

    def encode(self, clip, positive_prompt: str, negative_prompt: str):
        positive_tokens = clip.tokenize(positive_prompt or "")
        negative_tokens = clip.tokenize(negative_prompt or "")
        positive = clip.encode_from_tokens_scheduled(positive_tokens)
        negative = clip.encode_from_tokens_scheduled(negative_tokens)
        return (positive, negative)


class IllustriousPromptResultViewer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive_prompt": ("STRING", {"multiline": True, "forceInput": True}),
                "negative_prompt": ("STRING", {"multiline": True, "forceInput": True}),
                "raw_response": ("STRING", {"multiline": True, "forceInput": True}),
            }
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "raw_response")
    FUNCTION = "show"
    CATEGORY = "DeepSeek/Illustrious"
    OUTPUT_NODE = True

    def show(
        self,
        positive_prompt: str,
        negative_prompt: str,
        raw_response: str,
    ):
        combined_preview = (
            "[Positive Prompt]\n"
            f"{positive_prompt or ''}\n\n"
            "[Negative Prompt]\n"
            f"{negative_prompt or ''}\n\n"
            "[Raw Response]\n"
            f"{raw_response or ''}"
        )
        return {
            "ui": {
                "string": [combined_preview],
            },
            "result": (positive_prompt or "", negative_prompt or "", raw_response or ""),
        }


NODE_CLASS_MAPPINGS = {
    "DeepSeekIllustriousPromptGenerator": DeepSeekIllustriousPromptGenerator,
    "DualPromptCLIPEncode": DualPromptCLIPEncode,
    "IllustriousPromptResultViewer": IllustriousPromptResultViewer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DeepSeekIllustriousPromptGenerator": "DeepSeek Illustrious Prompt",
    "DualPromptCLIPEncode": "Dual Prompt CLIP Encode",
    "IllustriousPromptResultViewer": "Illustrious Prompt Result Viewer",
}
