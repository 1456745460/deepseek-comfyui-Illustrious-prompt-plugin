# ComfyUI DeepSeek Illustrious Prompter

一个面向 ComfyUI 的自定义节点插件，用 DeepSeek 把中文需求描述整理成适合 Illustrious 使用的英文正向/负向提示词，并同步提供中文翻译字段；可将英文提示词直接编码成 `CONDITIONING` 接到采样流程。

当前版本主节点显示名：

- `DeepSeek Illustrious Prompt - v1.2`

## 界面示例

主节点界面示例：

![DeepSeek Illustrious Prompt UI](docs/images/iShot_2026-07-06_11.11.05.png)

风格预设切换示例：

![Style Preset UI](docs/images/iShot_2026-07-06_11.11.18.png)

## 当前功能

- 从 `config/deepseek_config.ini` 读取 DeepSeek 的 `api_key`、`base_url`、`model`
- 从 `config/deepseek_config.ini` 读取多套 `style_preset` 对应的 `system_prompt`
- 支持在节点里直接覆盖 `system_prompt`
- 支持基础正向提示词、基础负向提示词与模型结果合并
- 输出英文正/负向提示词，以及对应中文翻译字段
- 支持 `json_retry_count`，当模型返回非合法 JSON 时自动重试
- 当返回被截断（如 `finish_reason=length` 或 JSON 未闭合）时，自动提高 `max_tokens` 并重试
- 执行成功后，前端会把最终实际使用的 `max_tokens` 写回节点控件
- 支持接入 `LLM_CONFIG`，可与 `ComfyUI-LLMs-Toolkit` 复用配置
- 支持把英文正负提示词直接编码为 `CONDITIONING`
- 支持结果查看节点，直接显示英文提示词、中文翻译和原始返回

## 节点说明

### 1. `DeepSeek Illustrious Prompt - v1.2`

输出：

- `positive_prompt`
- `positive_prompt_chinese`
- `negative_prompt`
- `negative_prompt_chinese`
- `raw_response`

字段说明：

- `positive_prompt`：英文正向提示词，用于 CLIP 编码和实际出图
- `positive_prompt_chinese`：英文正向提示词的中文翻译，便于核对语义
- `negative_prompt`：英文负向提示词，用于 CLIP 编码和实际出图
- `negative_prompt_chinese`：英文负向提示词的中文翻译，便于核对语义
- `raw_response`：模型原始返回内容

`required` 参数：

- `model_name`
  可选 `deepseek-v4-flash`、`deepseek-v4-pro`、`custom`
- `custom_model`
  当 `model_name=custom` 时使用
- `system_prompt`
  当前节点使用的系统提示词。为空时，会自动读取当前 `style_preset` 对应的配置文件内容
- `quality_style_lora_prompt`
  质量/画风/Lora 提示词输入框，默认带当前常用质量与画风词，可手动编辑；会前置于最终英文正向提示词
- `base_positive_prompt`
  强制追加到质量/画风词之后、AI 生成内容之前的基础正向条件
- `base_negative_prompt`
  强制拼接到最终英文负向提示词前面
- `description`
  你的中文需求描述
- `style_preset`
  当前配置中支持：
  `illustrious-general`、`illustrious-anime`、`illustrious-portrait`、`illustrious-nsfw`、`illustrious-sweet`、`illustrious-photo`、`illustrious-poster`、`illustrious-chinese`、`illustrious-cyberpunk`、`illustrious-fantasy`、`illustrious-idol`、`illustrious-horror`
- `json_retry_count`
  当模型返回内容无法解析为目标 JSON 时的自动重试次数，默认 `3`
- `temperature`
  采样温度，默认 `0.5`
- `max_tokens`
  初始最大输出长度，默认 `2000`，范围 `128 ~ 8192`
  若输出被截断，会在该值基础上自动提升并重试；成功后 UI 会写回最终值

`optional` 参数：

- `base_url`
  默认 `https://api.deepseek.com/v1`
- `llm_config`
  接入外部 LLM 配置时使用

处理逻辑：

- 如果连接了 `llm_config`，优先使用 `llm_config` 里的 `api_key`、`base_url`、`model`
- 如果没有连接 `llm_config`，优先使用 `config/deepseek_config.ini`
- 如果 `system_prompt` 输入框为空，则自动读取当前 `style_preset` 在配置文件里的内容
- 模型返回后会尝试解析 JSON；如果不是合法 JSON，会做容错提取
- 若判定为输出截断，会自动提高 `max_tokens` 并重试（最多额外提升 3 次，上限 `8192`）
- 若仍然无法提取到可用的 `positive_prompt` / `negative_prompt`，会按 `json_retry_count` 自动重试
- 中文字段 `positive_prompt_chinese` / `negative_prompt_chinese` 会一并解析；缺失时返回空字符串
- 最终英文结果会做基础清洗，去掉代码块、`<think>` 和重复标签
- 中文翻译字段会做更轻量的清洗，尽量保留中文语义

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
- 中文字段不参与 CLIP 编码，仅用于查看和核对

### 3. `Illustrious Prompt Result Viewer`

输入：

- `positive_prompt`
- `positive_prompt_chinese`
- `negative_prompt`
- `negative_prompt_chinese`
- `raw_response`

输出：

- `positive_prompt`
- `positive_prompt_chinese`
- `negative_prompt`
- `negative_prompt_chinese`
- `raw_response`

用途：

- 在节点内部直接显示生成结果
- 同时展示英文提示词和中文翻译
- 保存工作流后再次打开，结果内容仍可保留

## 配置文件

配置文件路径：

```bash
ComfyUI/custom_nodes/deepseek-comfyui-Illustrious-prompt-plugin/config/deepseek_config.ini
```

示例：

```ini
[deepseek]
api_key = sk-xxxxxxxxxxxxxxxx
base_url = https://api.deepseek.com/v1
model = deepseek-v4-flash
json_retry_count = 3

[system_prompts]
illustrious-general =
    在这里填写 general 的 system prompt
illustrious-anime =
    在这里填写 anime 的 system prompt
illustrious-portrait =
    在这里填写 portrait 的 system prompt
illustrious-nsfw =
    在这里填写 nsfw 的 system prompt
illustrious-sweet =
    在这里填写 sweet 的 system prompt
illustrious-photo =
    在这里填写 photo 的 system prompt
illustrious-poster =
    在这里填写 poster 的 system prompt
illustrious-chinese =
    在这里填写 chinese 的 system prompt
illustrious-cyberpunk =
    在这里填写 cyberpunk 的 system prompt
illustrious-fantasy =
    在这里填写 fantasy 的 system prompt
illustrious-idol =
    在这里填写 idol 的 system prompt
illustrious-horror =
    在这里填写 horror 的 system prompt
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
- `system_prompts`
  风格预设对应的系统提示词来源

说明：

- `INI` 支持多行原样书写 `system_prompt`，不再需要手动写 `\n`、`\"` 转义
- 切换 `style_preset` 时，前端会自动把对应的 `system_prompt` 带到节点输入框
- 如果你想完全自己控制提示词，也可以直接在节点里改 `system_prompt`
- 配置中的 system prompt 已要求模型输出 4 字段 JSON：
  - `positive_prompt`
  - `positive_prompt_chinese`
  - `negative_prompt`
  - `negative_prompt_chinese`

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
2. `DeepSeek Illustrious Prompt - v1.2`
3. `Dual Prompt CLIP Encode`
4. `Illustrious Prompt Result Viewer`（可选）
5. `KSampler`
6. `VAE Decode`

连接方式：

- `Load Checkpoint.clip` -> `Dual Prompt CLIP Encode.clip`
- `DeepSeek Illustrious Prompt - v1.2.positive_prompt` -> `Dual Prompt CLIP Encode.positive_prompt`
- `DeepSeek Illustrious Prompt - v1.2.negative_prompt` -> `Dual Prompt CLIP Encode.negative_prompt`
- `Dual Prompt CLIP Encode.positive` -> `KSampler.positive`
- `Dual Prompt CLIP Encode.negative` -> `KSampler.negative`
- 中文字段 `positive_prompt_chinese` / `negative_prompt_chinese` 可接到结果查看节点，不参与 CLIP 编码
- `raw_response` 也可接到结果查看节点，方便排查模型原始输出

### 方案 B：配合 `ComfyUI-LLMs-Toolkit`

1. 安装 `ComfyUI-LLMs-Toolkit`
2. 使用它的 `LLMs Loader` 配置 `api_key`、`base_url`、`model`
3. 把 `LLMs Loader.llm_config` 接到本插件的 `llm_config`

这样可以复用 LLM 配置，不必在多个节点中重复填写。

## 模型返回 JSON 格式

这个插件默认要求模型返回：

```json
{
  "positive_prompt": "英文正向提示词",
  "positive_prompt_chinese": "翻译中文后的正向提示词",
  "negative_prompt": "英文负向提示词",
  "negative_prompt_chinese": "翻译中文后的负向提示词"
}
```

说明：

- 英文提示词用于实际出图
- 中文翻译字段用于人工核对，不直接进入 CLIP 编码
- 中文字段应忠实对应英文提示词语义

## 关于 JSON 解析失败与截断重试

大模型有时会返回不完全规范的内容，当前实现会按以下顺序处理：

1. 直接按 JSON 解析
2. 尝试从返回文本里提取 JSON 对象
3. 尝试正则提取：
   - `positive_prompt`
   - `positive_prompt_chinese`
   - `negative_prompt`
   - `negative_prompt_chinese`
4. 如果判定为输出被截断（如 `finish_reason=length`、JSON 括号未闭合等），自动提高 `max_tokens` 后重试
5. 如果仍失败，则按 `json_retry_count` 自动重试
6. 重试后仍失败才最终报错

`max_tokens` 自动提升规则：

- 起始值：节点上的 `max_tokens`
- 提升幅度：`max(当前 * 1.5, 当前 + 512)`
- 最多额外提升：`3` 次
- 上限：`8192`
- 成功后：前端 `onExecuted` 会把最终实际使用的 `max_tokens` 写回控件

## 示例工作流

仓库 `examples/` 目录中包含示例工作流，可直接导入测试：

- `examples/deeepseek.json`
  仅提示词生成 + 结果查看
- `examples/deepseek+illustrious.json`
  提示词生成 + CLIP 编码 + 采样出图

示例中：

- 英文正/负向提示词会进入编码和出图链路
- 中文翻译字段会接到结果查看节点

## 备注

- 默认 Base URL：`https://api.deepseek.com/v1`
- 默认配置文件：`config/deepseek_config.ini`
- 主节点默认标题：`DeepSeek Illustrious Prompt - v1.2`
- `max_tokens` 默认 `2000`，最大 `8192`
- CLIP 编码只使用英文字段；中文字段用于展示和核对
