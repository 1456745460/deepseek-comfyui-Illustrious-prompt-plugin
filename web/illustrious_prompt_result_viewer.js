import { app } from "/scripts/app.js";
import { ComfyWidgets } from "/scripts/widgets.js";

let systemPromptPresets = {
    "illustrious-general": "",
    "illustrious-anime": "",
    "illustrious-portrait": "",
    "illustrious-nsfw": "",
};

const loadSystemPromptPresets = async () => {
    try {
        const response = await fetch("/deepseek_illustrious_prompt/config", { cache: "no-store" });
        if (!response.ok) return;
        const data = await response.json();
        systemPromptPresets = {
            ...systemPromptPresets,
            ...(data?.system_prompts || {}),
        };
    } catch (error) {
        console.warn("Failed to load DeepSeek system prompts from config:", error);
    }
};

const DEEPSEEK_PROMPT_NODE_MIN_SIZE = [420, 760];
const RESULT_VIEWER_NODE_MIN_SIZE = [520, 720];
const DEEPSEEK_DEFAULTS = {
    model_name: "deepseek-v4-flash",
    style_preset: "illustrious-general",
    json_retry_count: 3,
    temperature: 0.5,
    max_tokens: 2000,
    base_url: "https://api.deepseek.com/v1",
};

const VALID_STYLE_PRESETS = new Set([
    "illustrious-general",
    "illustrious-anime",
    "illustrious-portrait",
    "illustrious-nsfw",
]);

const VALID_MODEL_NAMES = new Set(["deepseek-v4-flash", "deepseek-v4-pro", "custom"]);

app.registerExtension({
    name: "Comfy.IllustriousPromptResultViewer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "DeepSeekIllustriousPromptGenerator" || nodeData.name === "DeepSeek Illustrious Prompt") {
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

            const sanitizeNodeWidgets = (node) => {
                const modelWidget = getWidget(node, "model_name");
                if (modelWidget && !VALID_MODEL_NAMES.has(modelWidget.value)) {
                    setWidgetValue(modelWidget, DEEPSEEK_DEFAULTS.model_name);
                }

                const styleWidget = getWidget(node, "style_preset");
                if (styleWidget && !VALID_STYLE_PRESETS.has(styleWidget.value)) {
                    setWidgetValue(styleWidget, DEEPSEEK_DEFAULTS.style_preset);
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

                const nextValue = systemPromptPresets[preset];
                if (nextValue === undefined) return;
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
                const styleWidget = getWidget(this, "style_preset");
                const systemWidget = getWidget(this, "system_prompt");
                if (styleWidget && systemWidget && !systemWidget.value) {
                    applyPresetToNode(this, styleWidget.value, true);
                }
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

            const originalOnExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                const result = originalOnExecuted ? originalOnExecuted.apply(this, arguments) : undefined;

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
                const styleWidget = getWidget(this, "style_preset");
                if (styleWidget) {
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
