import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
import { ComfyWidgets } from "/scripts/widgets.js";

const DEFAULT_STYLE_PRESET = "storyboard-director";

// 缓存 presets
let systemPromptPresets = { [DEFAULT_STYLE_PRESET]: "" };

const getSystemPromptPresets = () => systemPromptPresets;

const getStylePresetKeys = () => {
    const keys = Object.keys(systemPromptPresets || {});
    return keys.length ? keys : [DEFAULT_STYLE_PRESET];
};

const loadSystemPromptPresets = async () => {
    try {
        const response = await fetch(
            `/deepseek_illustrious_prompt/config`,
            { cache: "no-store" }
        );
        if (!response.ok) return;
        const data = await response.json();
        const loaded = data?.system_prompts || {};
        if (loaded && typeof loaded === "object" && Object.keys(loaded).length > 0) {
            systemPromptPresets = { ...loaded };
        } else {
            systemPromptPresets = { [DEFAULT_STYLE_PRESET]: "" };
        }
    } catch (error) {
        console.warn("Failed to load DeepSeek system prompts:", error);
    }
};

const DEEPSEEK_PROMPT_NODE_MIN_SIZE = [420, 760];

// 各控件在 LiteGraph canvas 中分配的高度（像素），通过覆写 computeSize 生效
const WIDGET_CANVAS_HEIGHT = {
    quality_style_lora_prompt: 70, // 质量/画风/Lora，约三行
    base_positive_prompt: 46,   // 约两行
    base_negative_prompt: 46,   // 约两行
    system_prompt:        280,  // 大面积
    description:          130,  // 需求描述
};

const applyPromptWidgetHeights = (node) => {
    if (!node.widgets) return;
    for (const widget of node.widgets) {
        const fixedH = WIDGET_CANVAS_HEIGHT[widget.name];
        if (fixedH == null) continue;
        // 覆写 computeSize，让 LiteGraph 按此高度分配 canvas 空间
        widget.computeSize = function (width) {
            return [width, fixedH];
        };
    }
    // 通知 LiteGraph 重新计算布局
    node.setSize?.(node.computeSize?.() || node.size);
    node.setDirtyCanvas?.(true, true);
};
const RESULT_VIEWER_NODE_MIN_SIZE = [520, 720];
const DEEPSEEK_DEFAULTS = {
    model_name: "deepseek-v4-flash",
    style_preset: DEFAULT_STYLE_PRESET,
    json_retry_count: 3,
    temperature: 0.2,
    max_tokens: 2000,
    base_url: "https://api.deepseek.com/v1",
};

const isValidStylePreset = (value) => getStylePresetKeys().includes(value);

const VALID_MODEL_NAMES = new Set(["deepseek-v4-flash", "deepseek-v4-pro", "custom"]);

app.registerExtension({
    name: "Comfy.IllustriousPromptResultViewer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "DeepSeekIllustriousPromptGenerator" || nodeData.name === "DeepSeek Illustrious Prompt") {
            // 预加载 presets
            await loadSystemPromptPresets();

            const getWidget = (node, name) => node.widgets?.find((widget) => widget.name === name);

            const setWidgetValue = (widget, value) => {
                if (!widget) return;
                widget.value = value;
                if (widget.inputEl) {
                    widget.inputEl.value = value;
                    widget.inputEl.dispatchEvent(new Event("input", { bubbles: true }));
                    widget.inputEl.dispatchEvent(new Event("change", { bubbles: true }));
                }

                if (typeof widget.callback === "function") {
                    widget.callback(value);
                }
            };

            const syncStylePresetWidget = (node) => {
                const styleWidget = getWidget(node, "style_preset");
                if (!styleWidget) return;

                const keys = getStylePresetKeys();
                // 兼容不同 ComfyUI combo 控件结构，强制只保留当前配置中的预设
                if (styleWidget.options && typeof styleWidget.options === "object") {
                    if (Array.isArray(styleWidget.options.values)) {
                        styleWidget.options.values = keys;
                    } else if (Array.isArray(styleWidget.options)) {
                        styleWidget.options.length = 0;
                        keys.forEach((key) => styleWidget.options.push(key));
                    }
                }
                if (Array.isArray(styleWidget.values)) {
                    styleWidget.values = keys;
                }

                const fallback = keys[0] || DEEPSEEK_DEFAULTS.style_preset;
                if (!keys.includes(styleWidget.value)) {
                    setWidgetValue(styleWidget, fallback);
                }
            };

            const sanitizeNodeWidgets = (node) => {
                const modelWidget = getWidget(node, "model_name");
                if (modelWidget && !VALID_MODEL_NAMES.has(modelWidget.value)) {
                    setWidgetValue(modelWidget, DEEPSEEK_DEFAULTS.model_name);
                }

                const styleWidget = getWidget(node, "style_preset");
                if (styleWidget) {
                    syncStylePresetWidget(node);
                    if (!isValidStylePreset(styleWidget.value)) {
                        setWidgetValue(styleWidget, getStylePresetKeys()[0] || DEEPSEEK_DEFAULTS.style_preset);
                    }
                }

                const retryWidget = getWidget(node, "json_retry_count");
                const parsedRetry = Number(retryWidget?.value);
                if (retryWidget && !(Number.isInteger(parsedRetry) && parsedRetry >= 0 && parsedRetry <= 10)) {
                    setWidgetValue(retryWidget, DEEPSEEK_DEFAULTS.json_retry_count);
                }

                const tempWidget = getWidget(node, "temperature");
                const parsedTemp = Number(tempWidget?.value);
                if (tempWidget && !(Number.isFinite(parsedTemp) && parsedTemp >= 0.0 && parsedTemp <= 1.5)) {
                    setWidgetValue(tempWidget, DEEPSEEK_DEFAULTS.temperature);
                }

                const maxTokensWidget = getWidget(node, "max_tokens");
                const parsedMaxTokens = Number(maxTokensWidget?.value);
                if (maxTokensWidget && !(Number.isInteger(parsedMaxTokens) && parsedMaxTokens >= 128 && parsedMaxTokens <= 8192)) {
                    setWidgetValue(maxTokensWidget, DEEPSEEK_DEFAULTS.max_tokens);
                }

                const baseUrlWidget = getWidget(node, "base_url");
                if (baseUrlWidget && (typeof baseUrlWidget.value !== "string" || !baseUrlWidget.value.trim())) {
                    setWidgetValue(baseUrlWidget, DEEPSEEK_DEFAULTS.base_url);
                }
            };

            const applyPresetToNode = (node, preset, force = false) => {
                const styleWidget = getWidget(node, "style_preset");
                const systemWidget = getWidget(node, "system_prompt");
                if (!styleWidget || !systemWidget) return;

                const presets = getSystemPromptPresets();
                // 若 preset key 不存在，尝试取第一个 key 的值
                let nextValue = presets[preset];
                if (nextValue === undefined) {
                    const firstKey = Object.keys(presets)[0];
                    nextValue = firstKey !== undefined ? presets[firstKey] : "";
                }
                if (!force && systemWidget.value === nextValue) return;

                setWidgetValue(systemWidget, nextValue);

                const currentSize = Array.isArray(node.size) ? [...node.size] : [...DEEPSEEK_PROMPT_NODE_MIN_SIZE];
                const computedSize = node.computeSize?.() || currentSize;
                const nextWidth = Math.max(currentSize[0] || 0, computedSize[0] || 0, DEEPSEEK_PROMPT_NODE_MIN_SIZE[0]);
                const nextHeight = Math.max(currentSize[1] || 0, computedSize[1] || 0, DEEPSEEK_PROMPT_NODE_MIN_SIZE[1]);
                node.setSize?.([nextWidth, nextHeight]);
                node.setDirtyCanvas?.(true, true);
                app.graph.setDirtyCanvas(true, true);
            };

            const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const result = originalOnNodeCreated ? originalOnNodeCreated.apply(this, arguments) : undefined;
                const computedSize = this.computeSize?.() || DEEPSEEK_PROMPT_NODE_MIN_SIZE;
                this.setSize?.([
                    Math.max(computedSize[0] || 0, DEEPSEEK_PROMPT_NODE_MIN_SIZE[0]),
                    Math.max(computedSize[1] || 0, DEEPSEEK_PROMPT_NODE_MIN_SIZE[1]),
                ]);
                sanitizeNodeWidgets(this);
                applyPromptWidgetHeights(this);
                const styleWidget = getWidget(this, "style_preset");
                const systemWidget = getWidget(this, "system_prompt");
                if (styleWidget) {
                    if (!isValidStylePreset(styleWidget.value)) {
                        setWidgetValue(styleWidget, getStylePresetKeys()[0] || DEEPSEEK_DEFAULTS.style_preset);
                    }
                    if (systemWidget && (!systemWidget.value || !String(systemWidget.value).trim())) {
                        applyPresetToNode(this, styleWidget.value, true);
                    }
                }

                // 确保创建时就显示 thinking widget
                ensureThinkingWidget(this);

                // 监听 ComfyUI 执行事件，当本节点开始执行时启动流
                // ComfyUI api 会在 "executing" 事件中发送 detail = node_id (string)
                const self = this;
                const _execHandler = ({ detail }) => {
                    // detail 直接是 node_id 字符串
                    if (String(detail) === String(self.id)) {
                        startThinkingStream(self);
                    }
                };
                api.addEventListener("executing", _execHandler);
                self.__thinkingExecHandler = _execHandler;

                return result;
            };

            const originalOnWidgetChanged = nodeType.prototype.onWidgetChanged;
            nodeType.prototype.onWidgetChanged = function (name, value, oldValue, widget) {
                const result = originalOnWidgetChanged
                    ? originalOnWidgetChanged.apply(this, arguments)
                    : undefined;
                if (name === "style_preset") {
                    applyPresetToNode(this, value, true);
                }
                return result;
            };

            // ──────────────────────────────────────────────────────────
            // 实时 Thinking 预览：在节点底部添加只读文本区域
            // ──────────────────────────────────────────────────────────

            /** 确保节点有 thinking 预览 widget，返回 widget */
            const ensureThinkingWidget = (node) => {
                if (node.__thinkingWidget) return node.__thinkingWidget;

                // 创建 DOM 容器
                const container = document.createElement("div");
                container.style.cssText = [
                    "position:relative",
                    "width:100%",
                    "margin-top:4px",
                ].join(";");

                // 标题栏
                const header = document.createElement("div");
                header.style.cssText = [
                    "display:flex",
                    "align-items:center",
                    "justify-content:space-between",
                    "padding:2px 6px",
                    "background:#1a1a2e",
                    "border-radius:4px 4px 0 0",
                    "border:1px solid #4a4a7a",
                    "border-bottom:none",
                    "user-select:none",
                    "cursor:pointer",
                ].join(";");

                const titleSpan = document.createElement("span");
                titleSpan.style.cssText = "color:#9090cc;font-size:11px;font-weight:bold;letter-spacing:0.5px";
                titleSpan.textContent = "💭 DeepSeek Thinking";

                const statusDot = document.createElement("span");
                statusDot.style.cssText = "width:8px;height:8px;border-radius:50%;background:#444;display:inline-block;transition:background 0.3s";
                statusDot.title = "空闲";
                node.__thinkingStatusDot = statusDot;

                header.appendChild(titleSpan);
                header.appendChild(statusDot);
                container.appendChild(header);

                // 文本区
                const textarea = document.createElement("textarea");
                textarea.readOnly = true;
                textarea.placeholder = "等待 DeepSeek 思考...";
                textarea.style.cssText = [
                    "width:100%",
                    "min-height:120px",
                    "max-height:300px",
                    "box-sizing:border-box",
                    "resize:vertical",
                    "background:#0d0d1a",
                    "color:#b0b0e8",
                    "border:1px solid #4a4a7a",
                    "border-top:none",
                    "border-radius:0 0 4px 4px",
                    "padding:6px 8px",
                    "font-size:11px",
                    "line-height:1.5",
                    "font-family:monospace",
                    "white-space:pre-wrap",
                    "overflow-y:auto",
                    "outline:none",
                ].join(";");
                container.appendChild(textarea);
                node.__thinkingTextarea = textarea;

                // 折叠/展开
                let collapsed = false;
                header.addEventListener("click", () => {
                    collapsed = !collapsed;
                    textarea.style.display = collapsed ? "none" : "block";
                    titleSpan.textContent = collapsed ? "💭 DeepSeek Thinking ▶" : "💭 DeepSeek Thinking";
                });

                // 创建 ComfyUI DOM widget
                const domWidget = node.addDOMWidget(
                    "thinking_preview",
                    "div",
                    container,
                    {
                        getValue: () => textarea.value,
                        setValue: (v) => { textarea.value = v || ""; },
                        serialize: false,
                    }
                );

                node.__thinkingWidget = domWidget;
                node.__thinkingContainer = container;
                return domWidget;
            };

            /** 启动 SSE 流，将 thinking 内容实时追加到 textarea */
            const startThinkingStream = (node) => {
                // 关闭已有的连接
                if (node.__thinkingEvtSource) {
                    try { node.__thinkingEvtSource.close(); } catch (_) {}
                    node.__thinkingEvtSource = null;
                }

                const nodeId = String(node.id);
                ensureThinkingWidget(node);

                const textarea = node.__thinkingTextarea;
                const dot = node.__thinkingStatusDot;

                // 清空上一次内容
                if (textarea) {
                    textarea.value = "";
                    textarea.placeholder = "正在等待 DeepSeek 思考...";
                }
                if (dot) {
                    dot.style.background = "#ffaa00";
                    dot.title = "连接中...";
                }

                let reasoningBuf = "";
                let contentBuf = "";
                let hasReasoning = false;

                const url = `/deepseek_illustrious_prompt/thinking_stream?node_id=${encodeURIComponent(nodeId)}`;
                const evtSource = new EventSource(url);
                node.__thinkingEvtSource = evtSource;

                evtSource.onopen = () => {
                    if (dot) {
                        dot.style.background = "#00cc66";
                        dot.title = "流式接收中...";
                    }
                };

                evtSource.onmessage = (e) => {
                    let evt;
                    try { evt = JSON.parse(e.data); } catch (_) { return; }

                    const { type, text } = evt;

                    if (type === "done") {
                        evtSource.close();
                        node.__thinkingEvtSource = null;
                        if (dot) {
                            dot.style.background = "#4466cc";
                            dot.title = "完成";
                        }
                        if (textarea) {
                            textarea.placeholder = "";
                        }
                        return;
                    }

                    if (type === "retry") {
                        reasoningBuf = "";
                        contentBuf = "";
                        hasReasoning = false;
                        if (textarea) {
                            textarea.value = `[重试中: ${text}]\n`;
                        }
                        return;
                    }

                    if (type === "reasoning") {
                        if (!hasReasoning) {
                            hasReasoning = true;
                            if (textarea) {
                                textarea.value = "[reasoning]\n";
                            }
                        }
                        reasoningBuf += text;
                        if (textarea) {
                            textarea.value = "[reasoning]\n" + reasoningBuf;
                            if (!textarea.matches(":focus")) {
                                textarea.scrollTop = textarea.scrollHeight;
                            }
                        }
                    } else if (type === "content") {
                        contentBuf += text;
                        if (textarea) {
                            const prefix = hasReasoning ? "[reasoning]\n" + reasoningBuf + "\n\n[content]\n" : "[content]\n";
                            textarea.value = prefix + contentBuf;
                            if (!textarea.matches(":focus")) {
                                textarea.scrollTop = textarea.scrollHeight;
                            }
                        }
                    }
                };

                evtSource.onerror = () => {
                    evtSource.close();
                    node.__thinkingEvtSource = null;
                    if (dot) {
                        dot.style.background = "#cc4444";
                        dot.title = "连接中断";
                    }
                };
            };

            const originalOnRemoved = nodeType.prototype.onRemoved;
            nodeType.prototype.onRemoved = function () {
                if (this.__thinkingEvtSource) {
                    try { this.__thinkingEvtSource.close(); } catch (_) {}
                }
                if (this.__thinkingExecHandler) {
                    api.removeEventListener("executing", this.__thinkingExecHandler);
                }
                return originalOnRemoved ? originalOnRemoved.apply(this, arguments) : undefined;
            };

            const originalOnExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                const result = originalOnExecuted ? originalOnExecuted.apply(this, arguments) : undefined;

                // 执行完成：关闭可能残留的 SSE 连接
                if (this.__thinkingEvtSource) {
                    try { this.__thinkingEvtSource.close(); } catch (_) {}
                    this.__thinkingEvtSource = null;
                }
                if (this.__thinkingStatusDot) {
                    this.__thinkingStatusDot.style.background = "#4466cc";
                    this.__thinkingStatusDot.title = "完成";
                }

                let finalMaxTokens = undefined;
                if (message?.ui?.max_tokens !== undefined) {
                    finalMaxTokens = message.ui.max_tokens;
                } else if (message?.max_tokens !== undefined) {
                    finalMaxTokens = message.max_tokens;
                }

                if (Array.isArray(finalMaxTokens)) {
                    finalMaxTokens = finalMaxTokens[0];
                }

                const parsedMaxTokens = Number(finalMaxTokens);
                if (Number.isInteger(parsedMaxTokens) && parsedMaxTokens >= 128 && parsedMaxTokens <= 8192) {
                    const maxTokensWidget = getWidget(this, "max_tokens");
                    if (maxTokensWidget && Number(maxTokensWidget.value) !== parsedMaxTokens) {
                        setWidgetValue(maxTokensWidget, parsedMaxTokens);
                        this.setDirtyCanvas?.(true, true);
                        app.graph.setDirtyCanvas(true, true);
                    }
                }

                return result;
            };

            const originalOnConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (config) {
                const result = originalOnConfigure ? originalOnConfigure.apply(this, arguments) : undefined;
                const currentSize = Array.isArray(this.size) ? this.size : DEEPSEEK_PROMPT_NODE_MIN_SIZE;
                this.setSize?.([
                    Math.max(currentSize[0] || 0, DEEPSEEK_PROMPT_NODE_MIN_SIZE[0]),
                    Math.max(currentSize[1] || 0, DEEPSEEK_PROMPT_NODE_MIN_SIZE[1]),
                ]);
                sanitizeNodeWidgets(this);
                applyPromptWidgetHeights(this);
                const styleWidget = getWidget(this, "style_preset");
                if (styleWidget) {
                    syncStylePresetWidget(this);
                    applyPresetToNode(this, styleWidget.value, true);
                }
                return result;
            };
            return;
        }

        if (nodeData.name !== "IllustriousPromptResultViewer" && nodeData.name !== "Illustrious Prompt Result Viewer") return;

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated ? originalOnNodeCreated.apply(this, arguments) : undefined;

            this.serialize_widgets = true;

            const existingNodes = app.graph._nodes.filter((n) => n.type === nodeData.name);
            const widgetName = `${nodeData.name}_preview_${existingNodes.length}`;
            const widgetInfo = ComfyWidgets.STRING(
                this,
                widgetName,
                ["STRING", {
                    default: "",
                    placeholder: "Illustrious prompt result will appear here...",
                    multiline: true,
                }],
                app
            );

            this.__resultWidget = widgetInfo.widget || widgetInfo;
            if (this.__resultWidget?.inputEl) {
                this.__resultWidget.inputEl.readOnly = true;
                this.__resultWidget.inputEl.style.minHeight = "360px";
            }

            const computedSize = this.computeSize?.() || RESULT_VIEWER_NODE_MIN_SIZE;
            this.setSize?.([
                Math.max(computedSize[0] || 0, RESULT_VIEWER_NODE_MIN_SIZE[0]),
                Math.max(computedSize[1] || 0, RESULT_VIEWER_NODE_MIN_SIZE[1]),
            ]);
            return result;
        };

        const setWidgetValue = (widget, value) => {
            if (!widget) return;
            const finalValue = Array.isArray(value) ? value.join("\n") : (value || "");
            widget.value = finalValue;
            if (widget.inputEl) {
                widget.inputEl.value = finalValue;
            }
            app.graph.setDirtyCanvas(true);
        };

        const originalOnExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (originalOnExecuted) originalOnExecuted.apply(this, arguments);

            let textData = undefined;
            if (message?.ui?.string) {
                textData = message.ui.string;
            } else if (message?.string) {
                textData = message.string;
            } else if (Array.isArray(message)) {
                textData = message;
            }
            setWidgetValue(this.__resultWidget, textData);
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (config) {
            if (originalOnConfigure) originalOnConfigure.apply(this, arguments);
            const currentSize = Array.isArray(this.size) ? this.size : RESULT_VIEWER_NODE_MIN_SIZE;
            this.setSize?.([
                Math.max(currentSize[0] || 0, RESULT_VIEWER_NODE_MIN_SIZE[0]),
                Math.max(currentSize[1] || 0, RESULT_VIEWER_NODE_MIN_SIZE[1]),
            ]);
            if (!this.__resultWidget || !config?.widgets_values?.length) return;

            const index = this.widgets.findIndex((w) => w === this.__resultWidget);
            if (index !== -1 && config.widgets_values.length > index) {
                setWidgetValue(this.__resultWidget, config.widgets_values[index] || "");
            }
        };
    },
});
