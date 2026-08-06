import asyncio
import json

from .nodes.deepseek_illustrious_prompt import (
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    get_system_prompt_presets,
    get_thinking_stream,
)

try:
    from aiohttp import web
    from server import PromptServer

    @PromptServer.instance.routes.get("/deepseek_illustrious_prompt/config")
    async def deepseek_illustrious_prompt_config(request):
        return web.json_response({"system_prompts": get_system_prompt_presets()})

    @PromptServer.instance.routes.get("/deepseek_illustrious_prompt/thinking_stream")
    async def deepseek_thinking_stream(request):
        """
        SSE 端点：前端订阅后，实时接收指定 node_id 的 DeepSeek 思考过程。
        Query param: node_id
        事件格式: data: {"type": "reasoning"|"content"|"retry"|"done", "text": "..."}
        """
        node_id = request.rel_url.query.get("node_id", "")
        if not node_id:
            return web.Response(status=400, text="missing node_id")

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)

        loop = asyncio.get_event_loop()

        # 等待流被创建（节点开始执行时才会 create_thinking_stream，最多等 30s）
        q = None
        for _ in range(300):
            q = get_thinking_stream(node_id)
            if q is not None:
                break
            await asyncio.sleep(0.1)

        if q is None:
            # 超时：节点可能还未执行或已经结束
            await response.write(
                b"data: " + json.dumps({"type": "done", "text": ""}).encode("utf-8") + b"\n\n"
            )
            try:
                await response.write_eof()
            except Exception:
                pass
            return response

        # 持续从队列读取并推送
        try:
            while True:
                # 用 executor 做阻塞式 queue.get，避免阻塞 asyncio 事件循环
                try:
                    item = await loop.run_in_executor(None, lambda: q.get(timeout=1.0))
                except Exception:
                    # 超时：检查流是否还存在
                    if get_thinking_stream(node_id) is None:
                        # 流已关闭
                        await response.write(
                            b"data: " + json.dumps({"type": "done", "text": ""}).encode("utf-8") + b"\n\n"
                        )
                        break
                    # 客户端断开检测
                    if request.transport and request.transport.is_closing():
                        break
                    continue

                if item is None:
                    # SENTINEL：流正常结束
                    await response.write(
                        b"data: " + json.dumps({"type": "done", "text": ""}).encode("utf-8") + b"\n\n"
                    )
                    break

                evt_type, text = item
                payload = json.dumps({"type": evt_type, "text": text}, ensure_ascii=False)
                await response.write(b"data: " + payload.encode("utf-8") + b"\n\n")

                if request.transport and request.transport.is_closing():
                    break
        except Exception:
            pass
        finally:
            try:
                await response.write_eof()
            except Exception:
                pass

        return response

except Exception:
    import traceback
    traceback.print_exc()

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
