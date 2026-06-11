#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
AGENT_CONFIG_DIR = ROOT / "agent_config"
AGENT_SETTINGS_PATH = AGENT_CONFIG_DIR / "agent_settings.json"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    aliases: tuple[str, ...]


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "market",
        "市场 / 地区",
        ("市场", "地区", "国家", "销售市场", "目标市场", "market", "country", "region", "target market"),
    ),
    FieldSpec(
        "collection_date",
        "收集日期",
        ("收集日期", "整理日期", "日期", "date", "collection date"),
    ),
    FieldSpec(
        "product_name",
        "产品名",
        ("产品名", "产品名称", "商品名", "商品名称", "品名", "中文名", "product name", "name"),
    ),
    FieldSpec(
        "english_name",
        "英文名",
        ("英文名", "英文名称", "英文品名", "english name", "en name"),
    ),
    FieldSpec(
        "category",
        "类目",
        ("类目", "品类", "分类", "商品分类", "category", "product category"),
    ),
    FieldSpec(
        "spec",
        "规格",
        ("规格", "容量", "尺寸", "尺码", "净含量", "包装", "spec", "specification", "size", "volume"),
    ),
    FieldSpec(
        "colors",
        "色号",
        ("色号", "颜色", "款式", "可选颜色", "color", "colors", "shade", "shades", "variant"),
    ),
    FieldSpec(
        "action_time",
        "作用时间",
        ("作用时间", "生效时间", "使用时长", "停留时间", "染发时间", "action time", "duration"),
    ),
    FieldSpec(
        "regular_price",
        "日常价",
        ("日常价", "原价", "售价", "价格", "常规价", "regular price", "price", "list price"),
    ),
    FieldSpec(
        "promo_price",
        "活动价",
        ("活动价", "优惠价", "促销价", "折扣价", "到手价", "promo price", "sale price", "discount price"),
    ),
    FieldSpec(
        "top_selling_points",
        "TOP 3 核心卖点",
        ("top 3 核心卖点", "核心卖点", "卖点", "优势", "功效", "selling points", "benefits", "usp"),
    ),
    FieldSpec(
        "audience_pain_matrix",
        "目标人群 x 痛点矩阵",
        ("目标人群", "人群", "受众", "用户画像", "人群痛点", "audience", "target users", "persona"),
    ),
    FieldSpec(
        "pain_conversion_talk_tracks",
        "核心痛点与转化话术",
        (
            "核心痛点",
            "痛点",
            "痛点和转化话术",
            "痛点与转化话术",
            "痛点转化话术",
            "转化话术",
            "销售话术",
            "购买理由",
            "pain points",
            "talk tracks",
            "objections",
        ),
    ),
    FieldSpec(
        "tiktok_marketing_angles",
        "TikTok 营销推广切入点",
        (
            "tiktok 营销推广切入点",
            "tiktok角度",
            "tiktok 内容角度",
            "tiktok内容角度",
            "tiktok推广角度",
            "内容角度",
            "营销角度",
            "视频角度",
            "hook",
            "angles",
        ),
    ),
    FieldSpec(
        "market_keywords",
        "市场关键词参考",
        ("市场关键词", "关键词", "搜索词", "标签", "hashtags", "keywords", "search terms"),
    ),
    FieldSpec(
        "material_type_suggestions",
        "适配素材类型建议",
        ("素材类型", "素材建议", "拍摄素材", "适配素材", "material", "creative assets", "shooting ideas"),
    ),
    FieldSpec(
        "notes",
        "补充备注",
        ("备注", "补充", "其他", "注意事项", "notes", "remarks", "extra"),
    ),
)


FIELD_KEYS = tuple(spec.key for spec in FIELD_SPECS)
LABEL_TO_FIELD = {spec.label: spec.key for spec in FIELD_SPECS}

OUTPUT_FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("productNameZh", "中文名称", ()),
    FieldSpec("productNameLocal", "本地名称", ()),
    FieldSpec("country", "国家/地区", ()),
    FieldSpec("categories", "分类 ID", ()),
    FieldSpec("price", "价格", ()),
    FieldSpec("specifications", "规格列表", ()),
    FieldSpec("extendedAttributes", "扩展属性", ()),
    FieldSpec("keySellingPoints", "核心卖点", ()),
    FieldSpec("targetAudienceAndPainPoints", "目标用户", ()),
    FieldSpec("skus", "SKU 清单", ()),
)


def normalize_label(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("×", "x").replace("&", "and")
    return re.sub(r"[\s_/#\-|,，.。:：;；()（）\[\]【】]+", "", text)


ALIAS_TO_FIELD: dict[str, str] = {}
for spec in FIELD_SPECS:
    ALIAS_TO_FIELD[normalize_label(spec.key)] = spec.key
    ALIAS_TO_FIELD[normalize_label(spec.label)] = spec.key
    for alias in spec.aliases:
        ALIAS_TO_FIELD[normalize_label(alias)] = spec.key


def log(message: str) -> None:
    print(message, flush=True)


def safe_name(value: str, default: str = "product_project", max_length: int = 100) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)
    text = re.sub(r"_+", "_", text).strip(" ._")
    return (text[:max_length].strip(" ._") or default)


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"配置文件不是有效 JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"配置文件顶层必须是 JSON object: {path}")
    return data


def visible_items(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not str(key).startswith("_")}


def load_agent_config() -> dict[str, Any]:
    settings = read_json_object(AGENT_SETTINGS_PATH)
    config: dict[str, Any] = {}
    for section_name in ("output",):
        section = settings.get(section_name, {})
        if isinstance(section, dict):
            config.update(visible_items(section))
    return config


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        lines = []
        for item in value:
            item_text = stringify_value(item)
            if item_text:
                lines.append(f"- {item_text}")
        return "\n".join(lines).strip()
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            item_text = stringify_value(item)
            if item_text:
                lines.append(f"- {key}：{item_text}")
        return "\n".join(lines).strip()
    return str(value).strip()


def empty_profile() -> dict[str, str]:
    return {key: "" for key in FIELD_KEYS}


def normalize_profile(data: Any) -> dict[str, str]:
    if isinstance(data, dict) and isinstance(data.get("product_profile"), dict):
        data = data["product_profile"]
    if not isinstance(data, dict):
        data = {}

    profile = empty_profile()
    normalized_input = {normalize_label(str(key)): value for key, value in data.items()}
    for spec in FIELD_SPECS:
        value = data.get(spec.key)
        if value in (None, ""):
            value = data.get(spec.label)
        if value in (None, ""):
            for alias in spec.aliases:
                alias_value = normalized_input.get(normalize_label(alias))
                if alias_value not in (None, ""):
                    value = alias_value
                    break
        profile[spec.key] = stringify_value(value)
    return profile


def append_field(profile: dict[str, str], field: str, value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    if profile.get(field):
        profile[field] = f"{profile[field].rstrip()}\n{text}"
    else:
        profile[field] = text


def field_from_label(label: str, fuzzy: bool = True) -> str:
    normalized = normalize_label(label)
    exact = ALIAS_TO_FIELD.get(normalized)
    if exact:
        return exact
    if not fuzzy:
        return ""

    matches: list[tuple[int, str]] = []
    for alias, field in ALIAS_TO_FIELD.items():
        if len(alias) < 2:
            continue
        if alias in normalized or normalized in alias:
            matches.append((len(alias), field))
    if not matches:
        return ""
    matches.sort(reverse=True)
    return matches[0][1]


def split_label_value(line: str) -> tuple[str, str] | None:
    cleaned = line.strip().lstrip("-*• \t")
    match = re.match(r"^(.{1,48}?)(?:[:：=]| - | — )\s*(.*)$", cleaned)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def strip_ordering(line: str) -> str:
    return re.sub(r"^\s*(?:[-*•]|\d+[.)、]|[一二三四五六七八九十]+[、.])\s*", "", line).strip()


def classify_unlabeled_line(line: str) -> str:
    text = line.lower()
    if re.search(r"(rm|usd|\$|￥|¥|\d+\s*(元|块|ringgit|myr))", text):
        if any(word in text for word in ("促销", "优惠", "活动", "折扣", "到手", "promo", "sale", "discount")):
            return "promo_price"
        return "regular_price"
    if any(word in line for word in ("TikTok", "短视频", "达人", "种草", "直播", "内容", "钩子", "hook")):
        return "tiktok_marketing_angles"
    if any(word in line for word in ("关键词", "搜索词", "标签", "hashtag", "#")):
        return "market_keywords"
    if any(word in line for word in ("素材", "拍摄", "画面", "场景", "口播", "测评", "对比")):
        return "material_type_suggestions"
    if any(word in line for word in ("目标", "人群", "用户", "适合", "妈妈", "学生", "上班族", "女性", "男性")):
        return "audience_pain_matrix"
    if any(word in line for word in ("痛点", "烦恼", "问题", "顾虑", "转化", "话术")):
        return "pain_conversion_talk_tracks"
    if any(word in line for word in ("卖点", "优势", "功效", "效果", "特点")):
        return "top_selling_points"
    return "notes"


def parse_markdown_sections(text: str) -> dict[str, str]:
    profile = empty_profile()
    current_field = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if current_field:
            value = "\n".join(buffer).strip()
            if value:
                append_field(profile, current_field, value)
        buffer = []

    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line.strip())
        if heading:
            next_field = field_from_label(heading.group(1))
            if next_field:
                flush()
                current_field = next_field
                continue
        if current_field:
            buffer.append(line)
    flush()
    return profile


def parse_heuristic_profile(text: str, input_path: Path | None = None) -> dict[str, str]:
    profile = parse_markdown_sections(text)
    current_field = ""
    saw_any_label = any(value.strip() for value in profile.values())

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading:
            field = field_from_label(heading.group(1))
            if field:
                current_field = field
                saw_any_label = True
            continue

        label_value = split_label_value(line)
        if label_value:
            label, value = label_value
            field = field_from_label(label)
            if field:
                append_field(profile, field, value)
                current_field = field
                saw_any_label = True
                continue

        cleaned = strip_ordering(line)
        if current_field and (line.startswith(("-", "*", "•")) or re.match(r"^\d+[.)、]", line)):
            append_field(profile, current_field, f"- {cleaned}" if not cleaned.startswith("-") else cleaned)
            continue

        label_only = line.rstrip(":：").strip()
        field = field_from_label(strip_ordering(label_only), fuzzy=False) if len(strip_ordering(label_only)) <= 48 else ""
        if field:
            current_field = field
            saw_any_label = True
            continue

        append_field(profile, classify_unlabeled_line(line), line)

    if not saw_any_label and not profile["product_name"] and input_path:
        profile["product_name"] = input_path.stem
    if not profile["collection_date"]:
        profile["collection_date"] = datetime.now().strftime("%Y-%m-%d")
    return normalize_profile(profile)


def clean_list_item(value: str) -> str:
    return re.sub(r"^\s*(?:[-*•]|\d+[.)、]|[一二三四五六七八九十]+[、.])\s*", "", str(value or "")).strip()


def split_list_text(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    lines = [clean_list_item(line) for line in text.splitlines() if clean_list_item(line)]
    if len(lines) > 1:
        return lines
    if any(separator in text for separator in ("、", "，", ",")):
        parts = re.split(r"\s*[、,，]\s*", text)
        return [part.strip() for part in parts if part.strip()]
    return [text]


def split_category_text(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"\s*(?:>|/|›|»|、|,|，)\s*", text)
    return [part.strip() for part in parts if part.strip()]


def strip_price_currency(value: str) -> str:
    return str(value or "").strip()


def named_values_from_text(name: str, value: str, split_values: bool = False) -> list[dict[str, str]]:
    items = split_list_text(value) if split_values else [str(value or "").strip()]
    return [{"name": name, "value": item} for item in items if item]


def selling_point_from_line(line: str) -> dict[str, str]:
    text = clean_list_item(line)
    if not text:
        return {"title": "", "description": ""}
    label_value = split_label_value(text)
    if label_value:
        title, description = label_value
        return {"title": title.strip(), "description": description.strip()}
    match = re.match(r"^(.{2,24}?)[，,。；;]\s*(.+)$", text)
    if match:
        return {"title": match.group(1).strip(), "description": match.group(2).strip()}
    return {"title": text[:28].strip(), "description": text}


def build_target_rows(profile: dict[str, str]) -> list[dict[str, str]]:
    audience_items = split_list_text(profile.get("audience_pain_matrix", ""))
    pain_items = split_list_text(profile.get("pain_conversion_talk_tracks", ""))
    rows: list[dict[str, str]] = []

    for item in audience_items:
        label_value = split_label_value(item)
        if label_value:
            audience, pain = label_value
            rows.append({"targetAudience": audience, "corePainPoints": pain})
            continue
        pain = pain_items[len(rows)] if len(pain_items) > len(rows) else "；".join(pain_items)
        rows.append({"targetAudience": item, "corePainPoints": pain})

    if not rows:
        for item in pain_items:
            rows.append({"targetAudience": "", "corePainPoints": item})
    return rows


def build_skus(specifications: list[dict[str, str]], price: dict[str, str]) -> list[dict[str, Any]]:
    variant_specs = [
        item
        for item in specifications
        if item.get("name") in {"颜色", "色号", "款式", "容量", "规格"} and item.get("value")
    ]
    if not variant_specs:
        return []

    color_specs = [item for item in variant_specs if item.get("name") in {"颜色", "色号", "款式"}]
    base_specs = color_specs or variant_specs[:1]
    skus: list[dict[str, Any]] = []
    for index, item in enumerate(base_specs, start=1):
        skus.append(
            {
                "skuId": f"SKU{index:03d}",
                "attributes": {item["name"]: item["value"]},
                "price": {
                    "originalPrice": price.get("originalPrice", ""),
                    "promotionalPrice": price.get("promotionalPrice", ""),
                },
            }
        )
    return skus


def product_data_from_profile(profile: dict[str, str]) -> dict[str, Any]:
    price = {
        "originalPrice": strip_price_currency(profile.get("regular_price", "")),
        "promotionalPrice": strip_price_currency(profile.get("promo_price", "")),
    }
    specifications: list[dict[str, str]] = []
    specifications.extend(named_values_from_text("规格", profile.get("spec", "")))
    specifications.extend(named_values_from_text("色号", profile.get("colors", ""), split_values=True))

    extended_attributes: list[dict[str, str]] = []
    for name, key in [
        ("作用时间", "action_time"),
        ("TikTok 营销推广切入点", "tiktok_marketing_angles"),
        ("市场关键词参考", "market_keywords"),
        ("适配素材类型建议", "material_type_suggestions"),
        ("补充备注", "notes"),
    ]:
        value = str(profile.get(key, "") or "").strip()
        if value:
            extended_attributes.append({"name": name, "value": value})

    selling_points = [
        item
        for item in (selling_point_from_line(line) for line in split_list_text(profile.get("top_selling_points", "")))
        if item.get("title") or item.get("description")
    ]
    data = {
        "productNameZh": str(profile.get("product_name", "") or "").strip(),
        "productNameLocal": str(profile.get("english_name", "") or "").strip(),
        "country": str(profile.get("market", "") or "").strip(),
        "categories": split_category_text(profile.get("category", "")),
        "extendedAttributes": extended_attributes,
        "specifications": specifications,
        "skus": [],
        "price": price,
        "keySellingPoints": selling_points,
        "targetAudienceAndPainPoints": build_target_rows(profile),
    }
    data["skus"] = build_skus(specifications, price)
    return data


def normalize_product_data(data: dict[str, Any]) -> dict[str, Any]:
    data = data if isinstance(data, dict) else {}

    def text(key: str) -> str:
        return str(data.get(key, "") or "").strip()

    def list_of_dicts(key: str, allowed_keys: tuple[str, ...]) -> list[dict[str, Any]]:
        rows = data.get(key, [])
        if not isinstance(rows, list):
            return []
        clean_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            clean = {field: row.get(field, "") for field in allowed_keys}
            if any(str(value or "").strip() for value in clean.values()):
                clean_rows.append(clean)
        return clean_rows

    price_data = data.get("price", {})
    if not isinstance(price_data, dict):
        price_data = {}

    categories = data.get("categories", [])
    if isinstance(categories, str):
        categories = split_category_text(categories)
    elif not isinstance(categories, list):
        categories = []
    clean_categories: list[str] = []
    seen_categories: set[str] = set()
    for item in categories:
        category = str(item).strip()
        if category and category not in seen_categories:
            clean_categories.append(category)
            seen_categories.add(category)
    categories = clean_categories

    skus = data.get("skus", [])
    clean_skus: list[dict[str, Any]] = []
    if isinstance(skus, list):
        for row in skus:
            if not isinstance(row, dict):
                continue
            attributes = row.get("attributes", {})
            if isinstance(attributes, str):
                attributes = {"规格组合": attributes}
            if not isinstance(attributes, dict):
                attributes = {}
            price = row.get("price", {})
            if not isinstance(price, dict):
                price = {}
            clean = {
                "skuId": str(row.get("skuId", "") or "").strip(),
                "attributes": {str(key): str(value) for key, value in attributes.items() if str(value or "").strip()},
                "price": {
                    "originalPrice": str(price.get("originalPrice", "") or row.get("originalPrice", "") or "").strip(),
                    "promotionalPrice": str(price.get("promotionalPrice", "") or row.get("promotionalPrice", "") or "").strip(),
                },
            }
            if clean["skuId"] or clean["attributes"] or clean["price"]["originalPrice"] or clean["price"]["promotionalPrice"]:
                clean_skus.append(clean)

    return {
        "productNameZh": text("productNameZh"),
        "productNameLocal": text("productNameLocal"),
        "country": text("country"),
        "categories": categories,
        "extendedAttributes": list_of_dicts("extendedAttributes", ("name", "value")),
        "specifications": list_of_dicts("specifications", ("name", "value")),
        "skus": clean_skus,
        "price": {
            "originalPrice": str(price_data.get("originalPrice", "") or "").strip(),
            "promotionalPrice": str(price_data.get("promotionalPrice", "") or "").strip(),
        },
        "keySellingPoints": list_of_dicts("keySellingPoints", ("title", "description")),
        "targetAudienceAndPainPoints": list_of_dicts(
            "targetAudienceAndPainPoints",
            ("targetAudience", "corePainPoints"),
        ),
    }


def output_field_values_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    data = normalize_product_data(data)
    values: dict[str, Any] = {
        "productNameZh": data["productNameZh"],
        "productNameLocal": data["productNameLocal"],
        "country": data["country"],
        "categories": data["categories"],
        "price": data["price"],
        "specifications": data["specifications"],
        "extendedAttributes": data["extendedAttributes"],
        "keySellingPoints": data["keySellingPoints"],
        "targetAudienceAndPainPoints": data["targetAudienceAndPainPoints"],
        "skus": data["skus"],
    }
    fields = []
    for spec in OUTPUT_FIELD_SPECS:
        value = values.get(spec.key)
        if isinstance(value, list):
            display = f"{len(value)} 项" if value else ""
            filled = bool(value)
        elif isinstance(value, dict):
            filled_values = [item for item in value.values() if str(item or "").strip()]
            display = " / ".join(str(item) for item in filled_values)
            filled = bool(filled_values)
        else:
            display = str(value or "").strip()
            filled = bool(display)
        fields.append({"key": spec.key, "label": spec.label, "value": display, "filled": filled})
    return fields


def generate_target_audience_and_pain_points(data: dict[str, Any], minimum_count: int = 10) -> list[dict[str, str]]:
    data = normalize_product_data(data)
    product_name = data.get("productNameZh") or data.get("productNameLocal") or "该产品"
    country = data.get("country") or "目标市场"
    category = data["categories"][-1] if data.get("categories") else "该品类"
    original_price = data.get("price", {}).get("originalPrice", "")
    promo_price = data.get("price", {}).get("promotionalPrice", "")
    price_text = promo_price or original_price or "当前价格"
    selling_points = [item for item in data.get("keySellingPoints", []) if item.get("title") or item.get("description")]
    specs = [item for item in data.get("specifications", []) if item.get("name") or item.get("value")]
    attributes = [item for item in data.get("extendedAttributes", []) if item.get("name") or item.get("value")]

    rows: list[dict[str, str]] = []

    def add(audience: str, pain: str) -> None:
        audience = re.sub(r"\s+", " ", str(audience or "")).strip()
        pain = re.sub(r"\s+", " ", str(pain or "")).strip()
        if not audience or not pain:
            return
        key = (audience, pain)
        existing = {(row["targetAudience"], row["corePainPoints"]) for row in rows}
        if key not in existing:
            rows.append({"targetAudience": audience, "corePainPoints": pain})

    add(
        f"在{country}第一次购买{category}、担心踩雷的用户",
        f"不知道{product_name}是否真正适合自己的使用场景，怕买回来闲置或效果不符合预期。",
    )
    add(
        f"正在对比同类{category}价格、关注到手价的预算型买家",
        f"同类产品选择多但价格差异大，需要明确看到{price_text}对应的价值点，才愿意下单。",
    )
    add(
        f"被旧产品体验劝退、想换更省心方案的复购替换人群",
        f"之前买过同类产品但使用体验不稳定，希望这次能解决核心问题而不是重复踩坑。",
    )
    add(
        f"在短视频或直播间被种草、需要快速决策的{country}买家",
        f"被内容吸引但缺少清晰的规格、价格和卖点对照，容易犹豫后划走。",
    )

    for point in selling_points:
        title = str(point.get("title") or "").strip()
        description = str(point.get("description") or "").strip()
        if title:
            add(
                f"特别关注「{title}」的{category}需求人群",
                description or f"想解决「{title}」相关问题，但担心普通产品无法直接满足需求。",
            )

    for spec in specs[:4]:
        name = str(spec.get("name") or "规格").strip()
        value = str(spec.get("value") or "").strip()
        if value:
            add(
                f"对{name}有明确偏好的细分买家",
                f"购买前需要确认{value}是否匹配自己的使用习惯、空间条件或赠礼需求。",
            )

    for attribute in attributes[:4]:
        name = str(attribute.get("name") or "属性").strip()
        value = str(attribute.get("value") or "").strip()
        if value:
            add(
                f"会仔细看{name}参数的理性决策用户",
                f"担心页面只讲卖点不讲细节，需要通过「{value}」判断产品是否可靠。",
            )

    fallback_rows = [
        (
            f"需要送礼但不熟悉{category}细节的礼品型买家",
            "想买得体面又怕选错规格、价格或适用场景，需要页面直接说明适合谁、为什么值得送。",
        ),
        (
            f"习惯先收藏再比较的{country}平台用户",
            "下单前会反复比较详情页、评价和优惠力度，如果卖点不够明确就容易流失。",
        ),
        (
            f"对产品信息完整度敏感的谨慎型买家",
            "缺少规格、属性、SKU 和价格说明时，会担心售后麻烦或收到的版本不一致。",
        ),
        (
            f"追求省时省事的日常使用人群",
            f"不想花太多时间研究复杂参数，希望快速知道{product_name}能解决什么具体问题。",
        ),
        (
            f"准备在促销期下单的机会型买家",
            "看到优惠价后仍需要一个明确购买理由，否则会继续等折扣或转向竞品。",
        ),
        (
            f"容易受真实场景打动的内容平台用户",
            "只看参数不容易产生购买冲动，需要看到和自己生活状态匹配的痛点表达。",
        ),
    ]
    for audience, pain in fallback_rows:
        add(audience, pain)
        if len(rows) >= minimum_count:
            break
    return rows[: max(minimum_count, min(len(rows), 15))]


def table_cell(value: Any) -> str:
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value or "")
    text = text.replace("|", "\\|").replace("\n", "<br>")
    return text or "未填写"


def callout_table_rows(rows: list[list[Any]]) -> list[str]:
    return ["> | " + " | ".join(table_cell(item) for item in row) + " |" for row in rows]


def sku_attributes_text(attributes: dict[str, str]) -> str:
    if not attributes:
        return "未填写"
    return " + ".join(str(value) for value in attributes.values() if str(value).strip()) or "未填写"


def json_callout(data: dict[str, Any]) -> list[str]:
    lines = ["> [!note]- 点击展开 JSON 结构", "> ```json"]
    lines.extend(f"> {line}" for line in json.dumps(data, ensure_ascii=False, indent=4).splitlines())
    lines.append("> ```")
    return lines


def output_field_values(profile: dict[str, str]) -> list[dict[str, Any]]:
    data = product_data_from_profile(profile)
    values: dict[str, Any] = {
        "productNameZh": data["productNameZh"],
        "productNameLocal": data["productNameLocal"],
        "country": data["country"],
        "categories": data["categories"],
        "price": data["price"],
        "specifications": data["specifications"],
        "extendedAttributes": data["extendedAttributes"],
        "keySellingPoints": data["keySellingPoints"],
        "targetAudienceAndPainPoints": data["targetAudienceAndPainPoints"],
        "skus": data["skus"],
    }
    fields = []
    for spec in OUTPUT_FIELD_SPECS:
        value = values.get(spec.key)
        if isinstance(value, list):
            display = f"{len(value)} 项" if value else ""
            filled = bool(value)
        elif isinstance(value, dict):
            filled_values = [item for item in value.values() if str(item or "").strip()]
            display = " / ".join(str(item) for item in filled_values)
            filled = bool(filled_values)
        else:
            display = str(value or "").strip()
            filled = bool(display)
        fields.append({"key": spec.key, "label": spec.label, "value": display, "filled": filled})
    return fields


def product_data_to_markdown(data: dict[str, Any], include_empty: bool = True) -> str:
    data = normalize_product_data(data)
    title = data.get("productNameZh") or data.get("productNameLocal") or "产品信息"
    lines: list[str] = [
        f"# {title}",
        "",
        "---",
        "",
        "## 📌 基本信息",
        "",
        "> [!info]+ 产品标识",
        "> | 字段 | 内容 |",
        "> |------|------|",
        f"> | **中文名称** | {table_cell(data.get('productNameZh'))} |",
        f"> | **本地名称** | {table_cell(data.get('productNameLocal'))} |",
        f"> | **国家/地区** | {table_cell(data.get('country'))} |",
        f"> | **分类 ID** | `{table_cell(data.get('categories'))}` |",
        "",
        "---",
        "",
        "## 💰 价格",
        "",
        "> [!important]+ 定价",
        "> | | 金额 |",
        "> |------|------|",
        f"> | **原价** | {table_cell(data['price'].get('originalPrice'))} |",
        f"> | **促销价** | {table_cell(data['price'].get('promotionalPrice'))} |",
        "",
        "---",
        "",
        "## 📦 规格",
        "",
        "> [!example]+ 规格列表",
        ">",
        "> | 规格名 | 规格值 |",
        "> |--------|--------|",
    ]
    specification_rows = [[item.get("name", ""), item.get("value", "")] for item in data["specifications"]]
    lines.extend(callout_table_rows(specification_rows or [["未填写", "未填写"]]))
    lines.extend(["", "---", "", "## 🔬 扩展属性", "", "> [!example]+ 扩展属性", ">", "> | 属性名 | 属性值 |", "> |--------|--------|"])
    attribute_rows = [[item.get("name", ""), item.get("value", "")] for item in data["extendedAttributes"]]
    lines.extend(callout_table_rows(attribute_rows or [["未填写", "未填写"]]))
    lines.extend(["", "---", "", "## 🎯 核心卖点", ""])
    if data["keySellingPoints"]:
        for index, item in enumerate(data["keySellingPoints"], start=1):
            lines.extend(
                [
                    f"> [!tip]+ 卖点 {index}",
                    f"> **标题** {table_cell(item.get('title'))}",
                    ">",
                    f"> **描述** {table_cell(item.get('description'))}",
                    "",
                ]
            )
    else:
        lines.extend(["> [!tip]+ 未填写", "> 未填写", ""])
    lines.extend(["---", "", "## 👥 目标用户", "", "> [!info]+ 用户画像", ">", "> | 目标用户 | 核心痛点 |", "> |----------|----------|"])
    target_rows = [[item.get("targetAudience", ""), item.get("corePainPoints", "")] for item in data["targetAudienceAndPainPoints"]]
    lines.extend(callout_table_rows(target_rows or [["未填写", "未填写"]]))
    lines.extend(["", "---", "", "## 📋 SKU 清单", "", "> [!abstract]+ SKU 明细", ">", "> | SKU ID | 规格组合 | 原价 | 促销价 |", "> |--------|----------|------|--------|"])
    sku_rows = [
        [
            item.get("skuId", ""),
            sku_attributes_text(item.get("attributes", {})),
            item.get("price", {}).get("originalPrice", ""),
            item.get("price", {}).get("promotionalPrice", ""),
        ]
        for item in data["skus"]
    ]
    lines.extend(callout_table_rows(sku_rows or [["未填写", "未填写", "未填写", "未填写"]]))
    lines.extend(["", "---", "", "## 📊 JSON 数据参考", ""])
    lines.extend(json_callout(data))
    return "\n".join(lines).rstrip() + "\n"


def profile_to_markdown(profile: dict[str, str], include_empty: bool = True) -> str:
    return product_data_to_markdown(product_data_from_profile(profile), include_empty=include_empty)


def resolve_input_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def read_input(args: argparse.Namespace) -> tuple[str, Path | None]:
    input_value = args.input_file or args.input
    if args.stdin or not input_value:
        if sys.stdin.isatty():
            raise SystemExit("请提供产品基础信息 txt 路径，或使用 --stdin 从标准输入读取。")
        return sys.stdin.read().strip(), None

    path = resolve_input_path(input_value)
    if not path.exists():
        raise SystemExit(f"输入文件不存在: {path}")
    if not path.is_file():
        raise SystemExit(f"输入路径不是文件: {path}")
    return read_text(path), path


def collect_profile(raw_text: str, input_path: Path | None) -> tuple[dict[str, str], str]:
    return parse_heuristic_profile(raw_text, input_path), "local"


def resolve_output_path(profile: dict[str, str], input_path: Path | None, config: dict[str, Any], args: argparse.Namespace) -> Path:
    if args.output:
        output_path = Path(args.output).expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        return output_path.resolve()

    output_root_value = args.output_root or str(config.get("default_output_root") or "product")
    output_root = Path(output_root_value).expanduser()
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    label = (
        args.project_slug
        or profile.get("english_name")
        or profile.get("product_name")
        or (input_path.stem if input_path else "")
        or "product_project"
    )
    project_slug = safe_name(label)
    return (output_root / project_slug / "product_profile" / "current_product_profile.md").resolve()


def write_profile(profile: dict[str, str], output_path: Path, include_empty: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(profile_to_markdown(profile, include_empty=include_empty), encoding="utf-8")


def write_product_data(data: dict[str, Any], output_path: Path, include_empty: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(product_data_to_markdown(data, include_empty=include_empty), encoding="utf-8")


def print_summary(profile: dict[str, str], mode_used: str, output_path: Path) -> None:
    name = profile.get("english_name") or profile.get("product_name") or output_path.parent.parent.name
    filled = sum(1 for item in output_field_values(profile) if item["filled"])
    log(f"产品信息整理完成: {name}")
    log(f"整理模式: {mode_used}")
    log(f"已填写字段: {filled}/{len(OUTPUT_FIELD_SPECS)}")
    log(f"Markdown 输出: {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把产品基础信息 txt 自动整理成 BunnyAI 产品信息模板 Markdown。")
    parser.add_argument("input", nargs="?", help="产品基础信息 txt 文件路径；不填时从 stdin 读取。")
    parser.add_argument("--input-file", default="", help="产品基础信息 txt 文件路径，等同于位置参数。")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取产品基础信息。")
    parser.add_argument("--output", "-o", default="", help="指定输出 Markdown 文件路径。")
    parser.add_argument("--output-root", default="", help="默认项目输出根目录，留空使用 agent_config 里的 product。")
    parser.add_argument("--project-slug", default="", help="手动指定产品项目目录名。")
    parser.add_argument("--compact", action="store_true", help="只输出有内容的 Markdown 小节。")
    parser.add_argument("--dry-run", action="store_true", help="只整理和预览，不写入文件。")
    parser.add_argument("--print", dest="print_result", action="store_true", help="在终端打印生成的 Markdown。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_agent_config()
    raw_text, input_path = read_input(args)
    if not raw_text.strip():
        raise SystemExit("输入内容为空，无法整理产品信息。")

    profile, mode_used = collect_profile(raw_text, input_path)
    include_empty = bool(config.get("include_empty_sections", True)) and not args.compact
    output_path = resolve_output_path(profile, input_path, config, args)
    markdown = profile_to_markdown(profile, include_empty=include_empty)

    if args.print_result or args.dry_run:
        print(markdown)
    if not args.dry_run:
        write_profile(profile, output_path, include_empty=include_empty)
        print_summary(profile, mode_used, output_path)
    else:
        log(f"dry-run 完成，未写入文件。计划输出: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
