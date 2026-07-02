# ComfyUI DeepSeek Illustrious Prompter

一个面向 ComfyUI 的自定义节点包，用 DeepSeek API 把自然语言描述转换成可直接用于 Illustrious 的正向/负向提示词，并可直接编码为 `CONDITIONING` 接到采样链路，不需要手工复制粘贴。

## 功能

- 配置 `DeepSeek API Key`
- 选择模型：`deepseek-v4-flash`、`deepseek-v4-pro` 或自定义模型名
- 支持可编辑的长 `system_prompt`
- 输入自然语言描述
- 支持请求模式：`refresh` / `fixed`
- 返回正向提示词、负向提示词、原始模型返回
- 支持结果过滤：`none` / `basic` / `aggressive`
- 支持强制移除指定词
- 支持追加默认负面词
- 支持接入 `ComfyUI-LLMs-Toolkit` 的 `LLM_CONFIG`
- 支持直接编码为正负 `CONDITIONING`

## 节点

### 1. `DeepSeek Illustrious Prompt`

输出：

- `positive_prompt`
- `negative_prompt`
- `raw_response`

说明：

- 不接 `llm_config` 时，直接使用本节点里的 `api_key`、`base_url`、`model_name`
- 接了 `llm_config` 时，优先使用 `LLMs Loader` 输出的配置
- `system_prompt` 支持直接粘贴长规则提示词并随时修改
- 只保留一个主要需求输入框 `description`，不再要求额外英文输入
- `request_mode=refresh` 时每次都会重新请求 DeepSeek
- `request_mode=fixed` 时相同输入会复用上一次结果，不重复请求

### 2. `Dual Prompt CLIP Encode`

输入：

- `clip`
- `positive_prompt`
- `negative_prompt`

输出：

- `positive`
- `negative`

这个节点的作用是把第一步得到的正负提示词直接变成 `CONDITIONING`，然后接到采样器，不再需要复制到传统的 CLIP 文本框。

### 3. `Illustrious Prompt Result Viewer`

输入：

- `positive_prompt`
- `negative_prompt`
- `raw_response`

输出：

- `positive_prompt`
- `negative_prompt`
- `raw_response`

这个节点会把三段文本直接显示在节点内部，并通过前端 widget 持久化保存。切换工作流标签或保存再打开时，内容仍然会保留。

## 安装

### 方式一：GitHub 安装

```bash
cd ComfyUI/custom_nodes
git clone git@github.com:1456745460/deepseek-comfyui-Illustrious-prompt-plugin.git
```

然后重启 ComfyUI。

### 方式二：手动安装

把整个仓库目录复制到：

```bash
ComfyUI/custom_nodes/deepseek-comfyui-Illustrious-prompt-plugin
```

然后重启 ComfyUI。

## 示例工作流

仓库里的 `examples/` 目录包含：

- `deepseek+illustrious.json`
- `deepseek_illustrious_prompt_workflow_api.json`

## 推荐工作流

### 方案 A：独立使用

1. `Load Checkpoint`
2. `DeepSeek Illustrious Prompt`
3. `Dual Prompt CLIP Encode`
4. `KSampler`
5. `VAE Decode`

连接方式：

- `Load Checkpoint.clip` -> `Dual Prompt CLIP Encode.clip`
- `DeepSeek Illustrious Prompt.positive_prompt` -> `Dual Prompt CLIP Encode.positive_prompt`
- `DeepSeek Illustrious Prompt.negative_prompt` -> `Dual Prompt CLIP Encode.negative_prompt`
- `Dual Prompt CLIP Encode.positive` -> `KSampler.positive`
- `Dual Prompt CLIP Encode.negative` -> `KSampler.negative`

### 方案 B：结合 `ComfyUI-LLMs-Toolkit`

1. 安装 `ComfyUI-LLMs-Toolkit`
2. 用它的 `LLMs Loader` 填好 DeepSeek 的 API Key、模型、Base URL
3. 把 `LLMs Loader.llm_config` 接到本插件的 `llm_config`

这样 DeepSeek 的配置就可以复用，不必在两个节点里重复填写。

## 说明

- 默认 Base URL：`https://api.deepseek.com/v1`
- 默认系统提示词会强制要求模型返回 JSON，便于稳定解析
- 过滤模式会自动去掉代码块、`<think>`、重复词和多余格式
- `include_default_negative` 打开后，会自动补一组常见质量负面词

## 后续可扩展

如果你后面要继续做，我建议再加这几项：

- 把系统提示词做成可编辑字段
- 增加“只返回正向词”或“分角色/场景/风格多输出口”
- 增加 Illustrious 风格预设库
- 增加 prompt 历史缓存和一键复用
