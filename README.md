# 产品信息收集智能体

把产品基础信息整理成 BunnyAI 产品信息模板 Markdown。Web 界面以手动录入为主，只有「目标用户 / 核心痛点」按本地提示词逻辑生成。

默认输出位置：

```text
product/<国家>_<分类ID>_<产品中文名称>.md
```

`product/` 固定在本智能体文件夹内，用来集中存放各个产品的信息收集结果。Web 界面不会把结果写到外部目录；同名文件已存在时会自动追加序号，不覆盖旧文件。

## 快速使用

```bash
python3 product_info_agent.py samples/product_basic_info.txt
```

这个智能体只做本地规则整理，不调用 API，也不需要配置 Key。

## Web 界面

```bash
python3 product_info_agent_web.py --port 8791
```

打开：

```text
http://127.0.0.1:8791
```

页面只保留手动录入这一套输入方式：填写产品字段、生成目标用户与核心痛点、预览 Markdown、生成独立产品 Markdown。左侧填完后点击「提交」会自动生成目标用户/核心痛点并存储 Markdown。

左侧「产品库」会读取当前 `product/` 目录内已经存储的 Markdown 文件，显示已有产品和更新时间；点击产品库条目可以在右侧预览，提交新产品后列表会自动刷新，方便避免重复添加。
产品库标题右侧的文件夹按钮可以直接打开本地 `product/` 目录。

## macOS 安装包

生成给其他 Mac 使用的 zip：

```bash
./package_macos.sh
```

生成结果在 `dist/` 目录。把 zip 发给对方后，对方解压并双击：

```text
start_product_info_agent.command
```

即可启动本地网页界面。程序只使用 Python 标准库，不调用外部 API。

只预览不写文件：

```bash
python3 product_info_agent.py samples/product_basic_info.txt --dry-run
```

指定输出文件：

```bash
python3 product_info_agent.py /path/to/product.txt -o /path/to/产品信息.md
```

## 输入建议

Web 表单需要手动填写：中文名称、本地名称、国家/地区、分类 ID、价格、规格、扩展属性、核心卖点和 SKU 清单。

「目标用户 / 核心痛点」由页面按钮基于这些手动字段本地生成，生成后仍可在文本框中微调。

## 输出字段

生成的 Markdown 使用 BunnyAI 产品信息模板结构：

- 基本信息：中文名称、本地名称、国家/地区、分类 ID
- 价格：原价、促销价
- 规格：规格名、规格值
- 扩展属性：属性名、属性值
- 核心卖点：Callout 卡片
- 目标用户：目标用户、核心痛点
- SKU 清单：SKU ID、规格组合、原价、促销价
- JSON 数据参考：完整结构化参考

## 验证

```bash
python3 -m py_compile product_info_agent.py
python3 -m py_compile product_info_agent_web.py
python3 product_info_agent.py samples/product_basic_info.txt --dry-run
```
