import configparser
import json
import math
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
NODE_VERSION = "v1.2"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PLUGIN_ROOT / "config"
CONFIG_PATH = CONFIG_DIR / "deepseek_config.ini"
LEGACY_CONFIG_PATH = CONFIG_DIR / "deepseek_config.json"
STYLE_PRESET_KEYS = [
    "illustrious-general",
    "illustrious-anime",
    "illustrious-portrait",
    "illustrious-nsfw",
    "illustrious-sweet",
    "illustrious-photo",
    "illustrious-poster",
    "illustrious-chinese",
    "illustrious-cyberpunk",
    "illustrious-fantasy",
    "illustrious-idol",
    "illustrious-horror",
]

DEFAULT_SYSTEM_PROMPT = ""


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
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        def extract_field(field_name: str) -> str:
            patterns = [
                rf'"{field_name}"\s*:\s*"((?:\\.|[^"\\])*)"',
                rf"'{field_name}'\s*:\s*'((?:\\.|[^'\\])*)'",
                rf"{field_name}\s*:\s*\"((?:\\.|[^\"\\])*)\"",
                rf"{field_name}\s*:\s*'((?:\\.|[^'\\])*)'",
            ]
            for pattern in patterns:
                field_match = re.search(pattern, cleaned, flags=re.DOTALL | re.IGNORECASE)
                if field_match:
                    raw_value = field_match.group(1)
                    try:
                        return bytes(raw_value, "utf-8").decode("unicode_escape")
                    except UnicodeDecodeError:
                        return raw_value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
            return ""

        positive_prompt = extract_field("positive_prompt")
        negative_prompt = extract_field("negative_prompt")
        if positive_prompt or negative_prompt:
            return {
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
            }

        raise ValueError(f"模型返回中未找到合法 JSON 或可提取字段。原始返回: {cleaned[:500]}")


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


def _clean_prompt_text(text: str) -> str:
    if not text:
        return ""

    cleaned = _strip_think_blocks(text)
    cleaned = cleaned.replace("，", ", ").replace("；", ", ").replace("：", ": ")
    cleaned = re.sub(r"\s*\n+\s*", ", ", cleaned)
    cleaned = re.sub(r"^(positive_prompt|negative_prompt|prompt)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,")
    cleaned = _dedupe_tokens(cleaned)
    return cleaned.strip(" ,")


def _resolve_model(model_name: str, custom_model: str) -> str:
    if model_name == "custom":
        return custom_model.strip()
    return model_name.strip()


def _normalize_file_config(raw: Dict[str, Any], source_path: Path) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件内容必须是对象: {source_path}")

    system_prompts_raw = raw.get("system_prompts", {}) or {}
    if not isinstance(system_prompts_raw, dict):
        system_prompts_raw = {}

    try:
        json_retry_count = max(0, int(raw.get("json_retry_count", 3) or 0))
    except (TypeError, ValueError):
        json_retry_count = 3

    system_prompts = {
        preset: str(system_prompts_raw.get(preset, "") or "").strip()
        for preset in STYLE_PRESET_KEYS
    }

    return {
        "api_key": str(raw.get("api_key", "") or "").strip(),
        "base_url": str(raw.get("base_url", "") or "").strip(),
        "model": str(raw.get("model", "") or "").strip(),
        "json_retry_count": json_retry_count,
        "system_prompts": system_prompts,
    }


def _load_ini_file_config(path: Path) -> Dict[str, Any]:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as exc:
        raise ValueError(f"配置文件格式错误，请检查 {path}: {exc}") from exc

    deepseek_section = parser["deepseek"] if parser.has_section("deepseek") else {}
    system_prompts = {}
    if parser.has_section("system_prompts"):
        for preset in STYLE_PRESET_KEYS:
            system_prompts[preset] = str(parser.get("system_prompts", preset, fallback="") or "").strip()

    raw = {
        "api_key": deepseek_section.get("api_key", ""),
        "base_url": deepseek_section.get("base_url", ""),
        "model": deepseek_section.get("model", ""),
        "json_retry_count": deepseek_section.get("json_retry_count", 3),
        "system_prompts": system_prompts,
    }
    return _normalize_file_config(raw, path)


def _load_json_file_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件格式错误，请检查 {path}: {exc}") from exc

    return _normalize_file_config(raw, path)


def _load_file_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        return _load_ini_file_config(CONFIG_PATH)
    if LEGACY_CONFIG_PATH.exists():
        return _load_json_file_config(LEGACY_CONFIG_PATH)
    return {}


def get_system_prompt_presets() -> Dict[str, str]:
    file_config = _load_file_config()
    prompts = file_config.get("system_prompts", {}) or {}
    return {preset: str(prompts.get(preset, "") or "") for preset in STYLE_PRESET_KEYS}


def get_json_retry_count() -> int:
    file_config = _load_file_config()
    try:
        return max(0, int(file_config.get("json_retry_count", 3) or 0))
    except (TypeError, ValueError):
        return 3


def _resolve_config(
    base_url: str,
    model_name: str,
    custom_model: str,
    llm_config: Optional[Dict[str, Any]],
) -> Tuple[str, str, str]:
    file_config = _load_file_config()
    resolved_api_key = file_config.get("api_key", "")
    resolved_base_url = base_url.strip() or DEFAULT_BASE_URL
    resolved_model = _resolve_model(model_name, custom_model)

    if file_config.get("base_url"):
        resolved_base_url = file_config["base_url"]
    if file_config.get("model"):
        resolved_model = file_config["model"]

    if llm_config:
        resolved_api_key = llm_config.get("api_key", resolved_api_key).strip()
        resolved_base_url = llm_config.get("base_url", resolved_base_url).strip() or DEFAULT_BASE_URL
        resolved_model = llm_config.get("model", resolved_model).strip() or resolved_model

    return resolved_api_key, resolved_base_url, resolved_model


def _build_user_prompt(
    description: str,
    style_preset: str,
) -> str:
    return (
        "Generate an Illustrious-ready positive prompt and negative prompt.\n"
        "Return valid json only.\n"
        f"Style preset: {style_preset}\n"
        f"User description: {description.strip()}\n"
        "Keep the positive prompt tag-like, concise, visually rich, and suitable for direct image generation."
    )


class DeepSeekIllustriousPromptGenerator:
    @classmethod
    def INPUT_TYPES(cls):
        try:
            presets = list(_load_file_config().get("system_prompts", {}).keys())
        except Exception:
            presets = []
        if not presets:
            presets = list(STYLE_PRESET_KEYS)
        default_preset = presets[0] if presets else "illustrious-general"

        return {
            "required": {
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
                "base_positive_prompt": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "label": "Base Positive Prompt",
                        "placeholder": "这里填写强制追加到正向提示词里的基础条件",
                    },
                ),
                "base_negative_prompt": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "label": "Base Negative Prompt",
                        "placeholder": "这里填写强制追加到负向提示词里的基础条件",
                    },
                ),
                "description": ("STRING", {"default": "", "multiline": True, "placeholder": "输入你的中文需求描述"}),
                "style_preset": (
                    presets,
                    {"default": default_preset},
                ),
                "json_retry_count": ("INT", {"default": 3, "min": 0, "max": 10, "step": 1}),
                "temperature": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.5, "step": 0.05}),
                "max_tokens": ("INT", {"default": 2000, "min": 128, "max": 4096, "step": 1}),
            },
            "optional": {
                "base_url": ("STRING", {"default": DEFAULT_BASE_URL, "multiline": False}),
                "llm_config": ("LLM_CONFIG",),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return math.nan

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "raw_response")
    FUNCTION = "generate"
    CATEGORY = "DeepSeek/Illustrious"

    def generate(
        self,
        model_name: str,
        custom_model: str,
        system_prompt: str,
        base_positive_prompt: str,
        base_negative_prompt: str,
        description: str,
        style_preset: str,
        json_retry_count: int,
        temperature: float,
        max_tokens: int,
        base_url: str = DEFAULT_BASE_URL,
        llm_config: Optional[Dict[str, Any]] = None,
    ):
        if not description.strip():
            raise ValueError("description 不能为空。")

        resolved_api_key, resolved_base_url, resolved_model = _resolve_config(
            base_url, model_name, custom_model, llm_config
        )
        if not resolved_api_key:
            raise ValueError(f"未提供 DeepSeek API Key。请在 {CONFIG_PATH} 配置，或连接 LLM_CONFIG。")
        if not resolved_model:
            raise ValueError("模型名为空。请在节点中选择模型、填写 custom_model，或在配置文件/LLM_CONFIG 中设置 model。")

        file_system_prompts = get_system_prompt_presets()
        resolved_system_prompt = system_prompt.strip() or file_system_prompts.get(style_preset, "") or DEFAULT_SYSTEM_PROMPT

        payload = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": resolved_system_prompt},
                {
                    "role": "user",
                    "content": _build_user_prompt(
                        description=description,
                        style_preset=style_preset,
                    ),
                },
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        retry_count = max(0, int(json_retry_count if json_retry_count is not None else get_json_retry_count()))
        last_parse_error = None
        raw_response = ""

        for attempt in range(retry_count + 1):
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
            try:
                parsed = _extract_json_object(raw_response)
                break
            except ValueError as exc:
                last_parse_error = exc
                if attempt >= retry_count:
                    raise RuntimeError(
                        f"DeepSeek 返回内容多次无法解析为目标 JSON，已重试 {retry_count} 次。最后一次返回: {raw_response[:500]}"
                    ) from exc
        else:
            raise RuntimeError(f"DeepSeek 返回内容无法解析为目标 JSON: {str(last_parse_error)[:500]}")

        positive_prompt = _clean_prompt_text(parsed.get("positive_prompt", ""))
        negative_prompt = _clean_prompt_text(parsed.get("negative_prompt", ""))

        if base_positive_prompt.strip():
            positive_prompt = _clean_prompt_text(
                f"{base_positive_prompt.strip()}, {positive_prompt}" if positive_prompt else base_positive_prompt.strip()
            )

        if base_negative_prompt.strip():
            negative_prompt = _clean_prompt_text(
                f"{base_negative_prompt.strip()}, {negative_prompt}" if negative_prompt else base_negative_prompt.strip()
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
    "DeepSeekIllustriousPromptGenerator": f"DeepSeek Illustrious Prompt - {NODE_VERSION}",
    "DualPromptCLIPEncode": "Dual Prompt CLIP Encode",
    "IllustriousPromptResultViewer": "Illustrious Prompt Result Viewer",
}
