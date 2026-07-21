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
NODE_VERSION = "v1.6"
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
    "illustrious-photobook",
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
        positive_prompt_chinese = extract_field("positive_prompt_chinese")
        if positive_prompt or positive_prompt_chinese:
            return {
                "positive_prompt": positive_prompt,
                "positive_prompt_chinese": positive_prompt_chinese,
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


# 禁止乱加权重的通用词（子串匹配，小写）
_WEIGHT_DENY_SUBSTRINGS = (
    "masterpiece", "best quality", "amazing quality", "very aesthetic",
    "absurdres", "ultra-detailed", "ultra detailed", "highres", "high res",
    "lowres", "newest", "high quality", "normal quality", "worst quality",
    "detailed", "intricate", "beautiful", "aesthetic", "exquisite",
    "lighting", "rim light", "backlight", "sidelight", "soft light",
    "cinematic", "dramatic", "atmosphere", "moody", "ambient",
    "bokeh", "depth of field", "depth-of-field", "blur", "defocus",
    "background", "composition", "from above", "from below", "from side",
    "looking at viewer", "upper body", "close-up", "close up", "full body",
    "cowboy shot", "portrait", "wide angle", "dutch angle",
    "anime style", "illustration", "photorealistic", "realistic", "photo",
    "film grain", "hdr", "8k", "4k", "wallpaper", "official art",
    "game cg", "cel shading", "soft shading", "lineart",
    "volumetric", "particle", "sparkle", "glitter", "glow",
    "fog", "mist", "rain", "snow", "smoke", "dust",
    "colorful", "vivid", "saturation", "contrast",
    "1girl", "2girls", "3girls", "1boy", "2boys", "solo",
    "multiple girls", "multiple boys", "sharp focus", "highly detailed",
    "absurd res", "ultra-detailed eyes", "beautiful detailed",
    "perfect face", "perfect body", "detailed eyes", "detailed face",
    "soft focus", "studio lighting", "natural lighting", "neon light",
    "lens flare", "chromatic", "anisotropic", "ray tracing",
)

_MAX_ATTENTION_WEIGHTS = 3
_MIN_KEEP_WEIGHT = 1.10
_MAX_KEEP_WEIGHT = 1.30


def _is_weight_denied(content: str) -> bool:
    low = content.lower().strip()
    if not low:
        return True
    if any(denylist in low for denylist in _WEIGHT_DENY_SUBSTRINGS):
        return True
    # 过长短语 / 多概念串不适合加权
    if len(low) > 36 or len(low.split()) > 4:
        return True
    if "," in low or "/" in low or "|" in low:
        return True
    return False


def _snap_weight(value: float) -> float:
    """把权重收敛到克制的离散档位。"""
    if value < 1.175:
        return 1.15
    if value < 1.225:
        return 1.2
    if value < 1.275:
        return 1.25
    return 1.3


def _format_weight(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text


def _normalize_attention_weights(text: str, max_weights: int = _MAX_ATTENTION_WEIGHTS) -> str:
    """
    强制收敛括号权重：
    - 去掉无数值括号、多层括号
    - 禁止给质量/光影/氛围等通用词加权
    - 权重钳制到 1.15–1.3
    - 整段最多保留 max_weights 处权重
    """
    if not text:
        return ""

    # 匹配一层或多层括号/方括号 attention；支持嵌在短语中间
    pattern = re.compile(
        r"([(\[]+)\s*([^()\[\]:]+?)\s*(?::\s*(-?\d+(?:\.\d+)?))?\s*([)\]]+)"
    )

    matches = list(pattern.finditer(text))
    if not matches:
        return text

    candidates = []
    for idx, match in enumerate(matches):
        content = re.sub(r"\s+", " ", match.group(2)).strip(" ,")
        raw_weight = match.group(3)
        weight_val = None
        if raw_weight is not None:
            try:
                weight_val = float(raw_weight)
            except ValueError:
                weight_val = None

        keep_weight = None
        if weight_val is not None and weight_val > 0 and not _is_weight_denied(content):
            if weight_val >= _MIN_KEEP_WEIGHT:
                clamped = min(max(weight_val, _MIN_KEEP_WEIGHT), _MAX_KEEP_WEIGHT)
                keep_weight = _snap_weight(clamped)
                candidates.append((idx, content, keep_weight, len(content)))

    keep_map = {}
    if candidates:
        ranked = sorted(candidates, key=lambda item: (-item[2], item[3], item[0]))
        for item in ranked[: max(0, int(max_weights))]:
            keep_map[item[0]] = item[2]

    parts = []
    last = 0
    for idx, match in enumerate(matches):
        parts.append(text[last:match.start()])
        content = re.sub(r"\s+", " ", match.group(2)).strip(" ,")
        if idx in keep_map:
            parts.append(f"({content}:{_format_weight(keep_map[idx])})")
        else:
            parts.append(content)
        last = match.end()
    parts.append(text[last:])
    normalized = "".join(parts)
    normalized = re.sub(r"\s{2,}", " ", normalized)
    normalized = re.sub(r"\s*,\s*", ", ", normalized)
    normalized = re.sub(r"(?:,\s*){2,}", ", ", normalized)
    return normalized.strip(" ,")


def _clean_prompt_text(text: str) -> str:
    if not text:
        return ""

    cleaned = _strip_think_blocks(text)
    cleaned = cleaned.replace("，", ", ").replace("；", ", ").replace("：", ": ")
    cleaned = re.sub(r"\s*\n+\s*", ", ", cleaned)
    cleaned = re.sub(
        r"^(positive_prompt(?:_chinese)?|prompt)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,")
    cleaned = _dedupe_tokens(cleaned)
    cleaned = _normalize_attention_weights(cleaned)
    cleaned = _dedupe_tokens(cleaned)
    return cleaned.strip(" ,")


def _clean_chinese_prompt_text(text: str) -> str:
    """中文提示词清洗：保留中文语义，仅做基础整理；强制去掉括号权重。"""
    if not text:
        return ""

    cleaned = _strip_think_blocks(text)
    cleaned = re.sub(
        r"^(positive_prompt(?:_chinese)?|prompt)\s*[:：]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*\n+\s*", "，", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
    # 中文字段禁止保留权重
    cleaned = re.sub(r"[（(]([^（）()]*?)(?:\s*[:：]\s*-?\d+(?:\.\d+)?)?[）)]", r"\1", cleaned)
    cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
    return cleaned.strip(" ，,")



def _resolve_model(model_name: str, custom_model: str) -> str:
    if model_name == "custom":
        return custom_model.strip()
    return model_name.strip()


AUTO_MAX_TOKENS_CAP = 8192
AUTO_MAX_TOKEN_BOOSTS = 3


def _boost_max_tokens(current: int, cap: int = AUTO_MAX_TOKENS_CAP) -> int:
    """Incomplete response 时适度提高 max_tokens。"""
    current = max(1, int(current or 1))
    cap = max(current, int(cap or current))
    boosted = max(int(current * 1.5), current + 512)
    return min(cap, boosted)


def _is_response_incomplete(choice: Dict[str, Any], raw_response: str) -> bool:
    """判断模型输出是否因 token 上限等原因被截断。"""
    finish_reason = str(choice.get("finish_reason") or "").strip().lower()
    if finish_reason in {"length", "max_tokens", "max_output_tokens"}:
        return True

    text = _strip_think_blocks(raw_response or "")
    if not text:
        return False

    # 未闭合 JSON 对象，通常是输出中途被截断
    if text.count("{") > text.count("}"):
        return True
    if text.count("[") > text.count("]"):
        return True

    # 截断在字符串中间的常见形态
    stripped = text.rstrip()
    if stripped.endswith(('\\', ',', ':', '"')) and '{' in stripped:
        return True

    return False


def _has_usable_prompt_fields(parsed: Dict[str, Any]) -> bool:
    positive = str(parsed.get("positive_prompt", "") or "").strip()
    return bool(positive)


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
        "Generate an Illustrious-ready positive prompt.\n"
        "Also provide a Chinese translation for the positive prompt.\n"
        "Return valid json only with keys: "
        "positive_prompt, positive_prompt_chinese.\n"
        f"Style preset: {style_preset}\n"
        f"User description: {description.strip()}\n"
        "English positive prompt rules:\n"
        "- Use concise Danbooru-like English tags/phrases, not long story sentences.\n"
        "- Prefer concrete visual details over vague adjectives.\n"
        "- Order by importance: quality -> subject identity -> appearance -> pose -> clothing -> scene -> camera -> lighting -> mood.\n"
        "- Attention weight rules (mandatory):\n"
        "  * Default NO weights. Prefer 0 weighted tags.\n"
        "  * At most 0-3 weighted tags in the whole positive_prompt.\n"
        "  * Only short core-identity tags may be weighted, e.g. user-specified hair/eyes/race/signature prop.\n"
        "  * Allowed form only: (tag:1.15) / (tag:1.2) / (tag:1.25); hard cap 1.3.\n"
        "  * Never weight quality, style, lighting, atmosphere, camera, background, particles, or generic detail words.\n"
        "  * Never use bare (tag), nested ((tag)), (((tag))), or weights >= 1.4.\n"
        "- Chinese field: faithful translation, no attention weights."
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
                        "default": "lowres, bad anatomy, bad hands, extra fingers, missing fingers, fused fingers, malformed hands, mutated hands, extra limbs, deformed, poorly drawn face, wrong anatomy, bad proportions, blurry, watermark, text, logo, signature, worst quality, low quality, normal quality, monochrome, grayscale, cinematic lighting, film grain, dramatic shadows, movie style, hdr, high contrast, cinematic composition, color grading, lens flare, depth of field, bokeh, anamorphic, wide angle, dutch angle, intricate background, complex background",
                        "multiline": True,
                        "label": "Base Negative Prompt",
                        "placeholder": "这里填写强制使用的负面提示词（不由 AI 生成，直接输出）",
                    },
                ),
                "description": ("STRING", {"default": "", "multiline": True, "placeholder": "输入你的中文需求描述"}),
                "style_preset": (
                    presets,
                    {"default": default_preset},
                ),
                "json_retry_count": ("INT", {"default": 3, "min": 0, "max": 10, "step": 1}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.5, "step": 0.05}),
                "max_tokens": ("INT", {"default": 2000, "min": 128, "max": 8192, "step": 1}),
            },
            "optional": {
                "base_url": ("STRING", {"default": DEFAULT_BASE_URL, "multiline": False}),
                "llm_config": ("LLM_CONFIG",),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return math.nan

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "positive_prompt",
        "positive_prompt_chinese",
        "negative_prompt",
        "raw_response",
    )
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
            "response_format": {"type": "json_object"},
        }

        retry_count = max(0, int(json_retry_count if json_retry_count is not None else get_json_retry_count()))
        current_max_tokens = max(128, int(max_tokens or 128))
        token_cap = max(current_max_tokens, AUTO_MAX_TOKENS_CAP)
        max_token_boosts = AUTO_MAX_TOKEN_BOOSTS

        last_parse_error = None
        raw_response = ""
        parsed = None
        parse_failures = 0
        token_boosts = 0

        # 解析失败会重试；若判定为输出截断，则额外自动提高 max_tokens 再重试
        while True:
            payload["max_tokens"] = current_max_tokens
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

            choice = choices[0] if isinstance(choices[0], dict) else {}
            raw_response = choice.get("message", {}).get("content", "") if isinstance(choice, dict) else ""
            incomplete = _is_response_incomplete(choice, raw_response)

            # 只要判定输出被截断，就优先自动提高 max_tokens 再重试
            if incomplete and token_boosts < max_token_boosts and current_max_tokens < token_cap:
                next_max_tokens = _boost_max_tokens(current_max_tokens, token_cap)
                if next_max_tokens > current_max_tokens:
                    current_max_tokens = next_max_tokens
                    token_boosts += 1
                    continue

            try:
                candidate = _extract_json_object(raw_response)
                if not _has_usable_prompt_fields(candidate):
                    raise ValueError("模型返回 JSON 中未提取到可用的 positive_prompt")
                parsed = candidate
                break
            except ValueError as exc:
                last_parse_error = exc
                if parse_failures >= retry_count:
                    detail = (
                        f"DeepSeek 返回内容多次无法解析为目标 JSON，已重试 {retry_count} 次"
                        f"（其中因截断自动提高 max_tokens {token_boosts} 次，最终 max_tokens={current_max_tokens}）。"
                        f"最后一次返回: {raw_response[:500]}"
                    )
                    raise RuntimeError(detail) from exc
                parse_failures += 1

        if parsed is None:
            raise RuntimeError(
                f"DeepSeek 返回内容无法解析为目标 JSON: {str(last_parse_error)[:500]}"
            )

        positive_prompt = _clean_prompt_text(parsed.get("positive_prompt", ""))
        positive_prompt_chinese = _clean_chinese_prompt_text(parsed.get("positive_prompt_chinese", ""))
        negative_prompt = base_negative_prompt.strip()

        if base_positive_prompt.strip():
            positive_prompt = _clean_prompt_text(
                f"{base_positive_prompt.strip()}, {positive_prompt}" if positive_prompt else base_positive_prompt.strip()
            )

        # 把最终实际使用的 max_tokens 回传给前端，便于 onExecuted 写回控件
        return {
            "ui": {
                "max_tokens": [int(current_max_tokens)],
            },
            "result": (
                positive_prompt,
                positive_prompt_chinese,
                negative_prompt,
                raw_response,
            ),
        }


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
                "positive_prompt_chinese": ("STRING", {"multiline": True, "forceInput": True}),
                "negative_prompt": ("STRING", {"multiline": True, "forceInput": True}),
                "raw_response": ("STRING", {"multiline": True, "forceInput": True}),
            }
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "positive_prompt",
        "positive_prompt_chinese",
        "negative_prompt",
        "raw_response",
    )
    FUNCTION = "show"
    CATEGORY = "DeepSeek/Illustrious"
    OUTPUT_NODE = True

    def show(
        self,
        positive_prompt: str,
        positive_prompt_chinese: str,
        negative_prompt: str,
        raw_response: str,
    ):
        combined_preview = (
            "[Positive Prompt]\n"
            f"{positive_prompt or ''}\n\n"
            "[Positive Prompt Chinese]\n"
            f"{positive_prompt_chinese or ''}\n\n"
            "[Negative Prompt]\n"
            f"{negative_prompt or ''}\n\n"
            "[Raw Response]\n"
            f"{raw_response or ''}"
        )
        return {
            "ui": {
                "string": [combined_preview],
            },
            "result": (
                positive_prompt or "",
                positive_prompt_chinese or "",
                negative_prompt or "",
                raw_response or "",
            ),
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
