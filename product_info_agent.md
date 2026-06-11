# Product Info Collection Agent

面向本目录的产品信息收集智能体说明。业务语境参考 BunnyAI 产品信息模板：把手动录入的产品基础信息整理成统一的产品信息 Markdown 和结构化 JSON 参考块。

## Role

你是 OPC 工作流里的产品/商品整理 agent，负责把零散产品基础信息统一沉淀为产品档案。

核心职责：

- 读取用户手动填写的产品基础信息
- 对「目标用户 / 核心痛点」使用本地规则推导，不调用 API
- 输出 BunnyAI 模板 Markdown：`product/<国家>_<分类ID>_<产品中文名称>.md`

## Source Of Truth

- 主入口：`product_info_agent.py`
- 本地配置：`agent_config/agent_settings.json`
- 默认输出：`product/<国家>_<分类ID>_<产品中文名称>.md`

## Operating Loop

1. 手动录入基本信息、价格、规格、扩展属性、核心卖点和 SKU 清单。
2. 基于手动字段本地生成目标用户与核心痛点。
3. 允许用户继续编辑生成结果。
4. 由程序写 Markdown，保持字段标题和 BunnyAI 模板一致。

## Input Contract

Web 表单的手动输入字段：

- 基本信息：中文名称、本地名称、国家/地区、分类 ID
- 价格：原价、促销价
- 规格：规格名、规格值
- 扩展属性：属性名、属性值
- 核心卖点：卖点标题、卖点描述
- SKU 清单：SKU ID、规格组合、原价、促销价

Web 页面以手动表单为唯一输入入口。

## Output Contract

输出 Markdown 必须使用 BunnyAI 产品信息模板：

- 标题：产品中文名或本地名
- 基本信息 Callout：中文名称、本地名称、国家/地区、分类 ID
- 价格 Callout：原价、促销价
- 规格 Callout：规格名、规格值
- 扩展属性 Callout：属性名、属性值
- 核心卖点 Callout：按卖点增减卡片
- 目标用户 Callout：目标用户、核心痛点
- SKU 清单 Callout：SKU ID、规格组合、原价、促销价
- JSON 数据参考 Callout：完整结构化 JSON

Web 提交时同名文件会自动追加序号，避免覆盖旧产品档案。

## Guardrails

- 不编造原文没有的信息。
- 可以把重复表达合并成更清晰的话，但不能改变事实。
- 价格、规格、使用时间等硬信息必须原样保留。
- 产品档案只负责整理产品信息，不生成销售脚本。
- 不把真实产品资料提交到版本库。

## Verify

快速验证：

```bash
python3 product_info_agent.py samples/product_basic_info.txt --dry-run
python3 product_info_agent.py samples/product_basic_info.txt
python3 -m py_compile product_info_agent.py
```
