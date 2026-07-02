import { app } from "/scripts/app.js";
import { ComfyWidgets } from "/scripts/widgets.js";

app.registerExtension({
    name: "Comfy.IllustriousPromptResultViewer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
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

            this.setSize(this.computeSize());
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
            if (!this.__resultWidget || !config?.widgets_values?.length) return;

            const index = this.widgets.findIndex((w) => w === this.__resultWidget);
            if (index !== -1 && config.widgets_values.length > index) {
                setWidgetValue(this.__resultWidget, config.widgets_values[index] || "");
            }
        };
    },
});
