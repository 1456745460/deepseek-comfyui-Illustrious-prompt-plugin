# ComfyUI DeepSeek Illustrious Prompter

一个面向 ComfyUI 的自定义节点插件，用 DeepSeek 把中文需求描述整理成适合 Illustrious / Danbooru 风格出图的英文正向提示词，并同步提供中文翻译字段；可将英文提示词直接编码成 `CONDITIONING` 接到采样流程。

当前版本主节点显示名：

- `DeepSeek Illustrious Prompt - v1.8`

## 界面示例

文生图调用示例：

![DeepSeek Illustrious Prompt UI](docs/images/iShot_2026-07-30_10.42.23.png)

简单调用示例：

![Style Preset UI](docs/images/iShot_2026-07-30_10.43.33.png)

## 当前功能

- 从 `config/deepseek_config.ini` 读取 DeepSeek 的 `api_key`、`base_url`、`model`
- 从 `config/deepseek_config.ini` 读取多套 `style_preset` 对应的 `system_prompt`
- 支持在节点里直接覆盖 `system_prompt`；切换风格预设时自动带出对应配置
- 支持质量/画风/Lora 提示词前置、基础正向/负向提示词与模型结果合并
- 输出英文正/负向提示词，以及英文正向提示词的中文翻译字段
- 负向提示词由节点直接输出（`base_negative_prompt` 参数），不由 AI 生成
- 支持 `json_retry_count`，当模型返回非合法 JSON 时自动重试
- 当返回被截断（如 `finish_reason=length` 或 JSON 未闭合）时，自动提高 `max_tokens` 并重试
- 执行成功后，前端会把最终实际使用的 `max_tokens` 写回节点控件
- 支持 DeepSeek 思考模式（`enable_thinking`），可调节思考强度 `reasoning_effort`
- 调用 API 时使用 `response_format={"type": "json_object"}` 强制 JSON 输出
- 支持接入 `LLM_CONFIG`，可与 `ComfyUI-LLMs-Toolkit` 复用配置
- 支持把英文正负提示词直接编码为 `CONDITIONING`
- 支持结果查看节点，直接显示英文提示词、中文翻译和原始返回
- 内置提示词清洗：去重、去 `<think>` 代码块、归一化注意力权重

## 节点说明

### 1. `DeepSeek Illustrious Prompt - v1.8`

输出：

- `positive_prompt`
- `positive_prompt_chinese`
- `negative_prompt`
- `raw_response`

字段说明：

- `positive_prompt`：英文正向提示词（质量/画风/Lora 词 + 基础正向条件 + AI 生成 tags 的拼接结果），用于 CLIP 编码和实际出图
- `positive_prompt_chinese`：英文正向提示词的中文翻译，便于核对语义
- `negative_prompt`：英文负向提示词，直接来源于节点的 `base_negative_prompt` 参数（不由 AI 生成）
- `raw_response`：模型原始返回内容（含思考过程时一并附上）

`required` 参数：

- `model_name`
  可选 `deepseek-v4-flash`、`deepseek-v4-pro`、`custom`
- `custom_model`
  当 `model_name=custom` 时使用
- `system_prompt`
  当前节点使用的系统提示词。为空时，会自动读取当前 `style_preset` 对应的配置文件内容
- `quality_style_lora_prompt`
  质量/画风/Lora 提示词输入框，默认带常用质量与画风词及若干画师/Lora 触发词，可手动编辑；会前置于最终英文正向提示词
- `base_positive_prompt`
  强制追加到质量/画风词之后、AI 生成内容之前的基础正向条件
- `base_negative_prompt`
  强制使用的负面提示词（有缺省值，直接输出，不由 AI 生成）
- `description`
  你的中文需求描述
- `style_preset`
  当前支持预设（从配置文件动态读取）：
  `storyboard-director`（默认，完整的分镜导演预设）
- `json_retry_count`
  当模型返回内容无法解析为目标 JSON 时的自动重试次数，默认 `3`
- `temperature`
  采样温度，默认 `0.2`
- `max_tokens`
  最大输出长度，默认 `8192`，范围 `128 ~ 8192`
  若输出被截断，会在该值基础上自动提升并重试；成功后 UI 会写回最终值
- `enable_thinking`
  是否开启 DeepSeek 思考模式（thinking），默认开启
- `reasoning_effort`
  思考强度，可选 `high` / `medium` / `low`，默认 `high`

`optional` 参数：

- `base_url`
  默认 `https://api.deepseek.com/v1`
- `llm_config`
  接入外部 LLM 配置时使用

处理逻辑：

1. 配置优先级：`llm_config` > `config/deepseek_config.ini` > 节点默认值
2. 使用 `response_format={"type": "json_object"}` 调用 DeepSeek Chat Completions API
3. 模型返回 JSON 后尝试解析；如果不是合法 JSON，做容错提取（正则匹配 JSON 对象 / 按字段名提取）
4. 若判定为输出截断，自动提高 `max_tokens` 并重试（最多额外提升 3 次，上限 8192）
5. 若仍然无法提取到可用的 `positive_prompt`，按 `json_retry_count` 自动重试
6. 最终英文结果做基础清洗：去 `<think>` / 代码块、全角转半角、去重、归一化注意力权重
7. 中文翻译字段做轻量清洗，强制去掉括号权重，尽量保留中文语义
8. 最终 `positive_prompt` = `quality_style_lora_prompt` + `base_positive_prompt` + AI tags（拼接后清洗去重）
9. 最终 `negative_prompt` = 直接输出 `base_negative_prompt`

### 2. `Dual Prompt CLIP Encode`

输入：

- `clip`
- `positive_prompt`
- `negative_prompt`

输出：

- `positive`
- `negative`

用途：

- 将英文正向提示词和英文负向提示词直接编码为 `CONDITIONING`
- 不需要再手动复制到传统 CLIP 文本框

### 3. `Illustrious Prompt Result Viewer`

输入：

- `positive_prompt`
- `positive_prompt_chinese`
- `negative_prompt`
- `raw_response`

输出：

- `positive_prompt`
- `positive_prompt_chinese`
- `negative_prompt`
- `raw_response`

用途：

- 在节点内部直接显示生成结果，同时展示英文提示词和中文翻译
- 保存工作流后再次打开，结果内容仍可保留

## 配置文件

配置文件路径：

```bash
ComfyUI/custom_nodes/deepseek-comfyui-Illustrious-prompt-plugin/config/deepseek_config.ini
```

示例结构：

```ini
[deepseek]
api_key = sk-xxxxxxxxxxxxxxxx
base_url = https://api.deepseek.com/v1
model = deepseek-v4-flash
json_retry_count = 3

[system_prompts]
storyboard-director =
    在这里填写 storyboard-director 的 system prompt
```

字段说明：

- `api_key`
  必填，DeepSeek API Key
- `base_url`
  可选，默认 `https://api.deepseek.com/v1`
- `model`
  可选，默认模型名；如果节点里选择了别的模型，节点值会参与覆盖
- `json_retry_count`
  可选，默认 `3`
- `system_prompts` 下的每个 key 对应一个风格预设名称，value 为对应的系统提示词

说明：

- `INI` 支持多行原样书写 `system_prompt`，不需要手动写 `\n`、`\"` 转义
- 切换 `style_preset` 时，前端会自动把对应的 `system_prompt` 带到节点输入框
- 风格预设名称由配置文件动态决定，插件启动时自动读取
- 配置中的 system prompt 要求模型输出 JSON 包含两个字段：
  - `positive_prompt`（英文正向 tags）
  - `positive_prompt_chinese`（中文翻译）
- 负向提示词（`negative_prompt`）由节点 `base_negative_prompt` 参数直接提供，不由 AI 生成

## 安装

### 方式一：Git 安装

```bash
cd ComfyUI/custom_nodes
git clone git@github.com:1456745460/deepseek-comfyui-Illustrious-prompt-plugin.git
```

安装后重启 ComfyUI。

### 方式二：手动复制

把整个仓库目录复制到：

```bash
ComfyUI/custom_nodes/deepseek-comfyui-Illustrious-prompt-plugin
```

然后重启 ComfyUI。

## 推荐使用方式

### 方案 A：独立使用

1. `Load Checkpoint`
2. `DeepSeek Illustrious Prompt - v1.8`
3. `Dual Prompt CLIP Encode`
4. `Illustrious Prompt Result Viewer`（可选）
5. `KSampler`
6. `VAE Decode`

连接方式：

- `Load Checkpoint.clip` → `Dual Prompt CLIP Encode.clip`
- `DeepSeek Illustrious Prompt.positive_prompt` → `Dual Prompt CLIP Encode.positive_prompt`
- `DeepSeek Illustrious Prompt.negative_prompt` → `Dual Prompt CLIP Encode.negative_prompt`
- `Dual Prompt CLIP Encode.positive` → `KSampler.positive`
- `Dual Prompt CLIP Encode.negative` → `KSampler.negative`
- 中文字段 `positive_prompt_chinese` 可接到结果查看节点，不参与 CLIP 编码
- `raw_response` 也可接到结果查看节点，方便排查模型原始输出

### 方案 B：配合 `ComfyUI-LLMs-Toolkit`

1. 安装 `ComfyUI-LLMs-Toolkit`
2. 使用它的 `LLMs Loader` 配置 `api_key`、`base_url`、`model`
3. 把 `LLMs Loader.llm_config` 接到本插件的 `llm_config`

这样可以复用 LLM 配置，不必在多个节点中重复填写。

## 模型返回 JSON 格式

这个插件要求模型返回：

```json
{
  "positive_prompt": "英文正向提示词",
  "positive_prompt_chinese": "翻译中文后的正向提示词"
}
```

说明：

- 英文提示词用于实际出图
- 中文翻译字段用于人工核对，不直接进入 CLIP 编码
- 负向提示词由节点的 `base_negative_prompt` 参数提供，不由 AI 生成
- API 调用时使用 `response_format={"type": "json_object"}`，强制模型输出合法 JSON

## 关于 JSON 解析失败与截断重试

大模型有时会返回不完全规范的内容，当前实现会按以下顺序处理：

1. 直接按 JSON 解析
2. 尝试从返回文本里提取 JSON 对象
3. 尝试按字段名正则提取 `positive_prompt` 和 `positive_prompt_chinese`
4. 如果判定为输出被截断（如 `finish_reason=length`、JSON 括号未闭合等），自动提高 `max_tokens` 后重试
5. 如果仍失败，则按 `json_retry_count` 自动重试
6. 重试后仍失败才最终报错

`max_tokens` 自动提升规则：

- 起始值：节点上的 `max_tokens`
- 提升幅度：`max(当前 × 1.5, 当前 + 512)`
- 最多额外提升：`3` 次
- 上限：`8192`
- 成功后：前端 `onExecuted` 会把最终实际使用的 `max_tokens` 写回控件

## 提示词清洗功能

输出结果经过多层自动清洗：

- **去 `<think>` 代码块**：移除模型推理过程中的思考内容和代码块标记
- **去重**：基于小写归一化的 token 级去重，避免重复标签
- **注意力权重归一化**：
  - 保留有效权重格式 `(tag:0.1~1.99)`，丢弃异常值
  - 展开无权重括号 `(tag)` → `tag`
  - 展开多层嵌套括号 `((tag))` → `tag`
- **全角转半角**：中文全角符号自动转英文半角

## 示例工作流

仓库 `examples/` 目录中包含示例工作流，可直接导入测试：

- `examples/示例工作流.json`
  仅提示词生成 + 结果查看
- `examples/示例工作流2.json`
  提示词生成 + CLIP 编码 + 采样出图

## 备注

- 默认 Base URL：`https://api.deepseek.com/v1`
- 默认配置文件：`config/deepseek_config.ini`
- 主节点默认标题：`DeepSeek Illustrious Prompt - v1.8`
- `max_tokens` 默认 `8192`，最大 `8192`
- `temperature` 默认 `0.2`
- CLIP 编码只使用英文字段；中文字段用于展示和核对
- 负向提示词直接使用 `base_negative_prompt`，不由 AI 生成
