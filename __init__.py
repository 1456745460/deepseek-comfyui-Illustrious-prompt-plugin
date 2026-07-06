from .nodes.deepseek_illustrious_prompt import (
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    get_system_prompt_presets,
)

try:
    from aiohttp import web
    from server import PromptServer

    @PromptServer.instance.routes.get("/deepseek_illustrious_prompt/config")
    async def deepseek_illustrious_prompt_config(request):
        return web.json_response({"system_prompts": get_system_prompt_presets()})
except Exception:
    pass

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
