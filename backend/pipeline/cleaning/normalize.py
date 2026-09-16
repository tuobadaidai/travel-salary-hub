"""薪资/城市/经验/学历/币种归一化。所有规则函数纯函数、无副作用，便于单测。"""

import re

# ---------- 薪资解析 ----------

_NUM = r"(\d+(?:\.\d+)?)"

_MONTH_PATTERNS = [
    (re.compile(r"[·xX*×]\s*(\d{1,2})\s*薪"), None),  # "15-25K·14薪" → 捕获组取月数
    (re.compile(r"(\d{1,2})\s*薪"), None),
]


def parse_months(s: str | None) -> int:
    """从薪资串中解析薪月数，默认 12。"""
    if not s:
        return 12
    m = re.search(r"[·xX*×]\s*(\d{1,2})\s*薪", s)
    if m:
        v = int(m.group(1))
        return v if 12 <= v <= 24 else 12
    m = re.search(r"(\d{1,2})\s*薪", s)
    if m:
        v = int(m.group(1))
        return v if 12 <= v <= 24 else 12
    return 12


def parse_salary_k(s: str | None) -> tuple[float, float] | None:
    """解析 '15-25K' / '1.8-3万' / '25000-35000' → (low, high) 元/月。

    仅处理月薪表达；年薪表达（如 '30-42万/年'）返回 None，由调用方决定降级策略。
    """
    if not s:
        return None
    t = s.replace(",", "").replace("，", "").strip()

    # 年薪显式标注：先剥离 "/年" "·年" "年薪" 再按数值量级判断
    is_annual = bool(re.search(r"/\s*年|年薪|per\s*year|/yr", t, re.I))
    if is_annual:
        m = re.match(rf"{_NUM}\s*[-–~至]\s*{_NUM}\s*(万|k|K|千)?", t)
        if not m:
            return None
        low, high, unit = float(m.group(1)), float(m.group(2)), m.group(3)
        mult = 10000 if unit == "万" else 1000 if unit in ("k", "K", "千") else 1
        low *= mult
        high *= mult
        # 量级判断：>10万/月不合理，视为年薪数值
        if low >= 100000:
            return (low / 12, high / 12)
        return None

    m = re.match(rf"{_NUM}\s*[-–~至]\s*{_NUM}\s*(万|k|K|千)?", t)
    if not m:
        return None
    low, high, unit = float(m.group(1)), float(m.group(2)), m.group(3)
    if unit == "万":
        return (low * 10000, high * 10000)
    if unit in ("k", "K", "千"):
        return (low * 1000, high * 1000)
    # 无单位：按数值量级猜
    if low >= 10000:
        return (low, high)
    if low >= 100:  # "25000-35000" 类
        return (low, high)
    return (low * 1000, high * 1000)  # "15-25" 裸数字当 K


def monthly_to_annual(low: float, high: float, months: int = 12) -> tuple[float, float]:
    return (low * months, high * months)


# ---------- 城市归一化 ----------

_CITY_MAP = {
    "北京": ["北京", "Beijing"],
    "上海": ["上海", "Shanghai"],
    "深圳": ["深圳", "Shenzhen"],
    "广州": ["广州", "Guangzhou"],
    "杭州": ["杭州", "Hangzhou"],
    "成都": ["成都", "Chengdu"],
    "南京": ["南京", "Nanjing"],
    "武汉": ["武汉", "Wuhan"],
    "西安": ["西安", "Xian", "Xi'an"],
    "苏州": ["苏州", "Suzhou"],
    "重庆": ["重庆", "Chongqing"],
    "天津": ["天津", "Tianjin"],
    "长沙": ["长沙", "Changsha"],
    "厦门": ["厦门", "Xiamen"],
    "香港": ["香港", "Hong Kong", "HongKong", "HK"],
    "新加坡": ["新加坡", "Singapore"],
    "迪拜": ["迪拜", "Dubai"],
    "伦敦": ["伦敦", "London"],
    # DIDA 海外驻地（roster 实际工作地点）
    "雅加达": ["雅加达", "Jakarta", "印度尼西亚", "Indonesia"],
    "曼谷": ["曼谷", "泰国", "Bangkok", "Thailand"],
    "吉隆坡": ["吉隆坡", "马来西亚", "Kuala Lumpur", "Malaysia"],
    "东京": ["东京", "日本", "Tokyo", "Japan"],
    "首尔": ["首尔", "韩国", "Seoul", "Korea"],
    "马尼拉": ["马尼拉", "菲律宾", "Manila", "Philippines"],
    "胡志明市": ["胡志明", "越南", "Ho Chi Minh", "Vietnam"],
    "马德里": ["马德里", "西班牙", "Madrid", "Spain"],
    "巴黎": ["巴黎", "法国", "Paris", "France"],
    "柏林": ["柏林", "德国", "Berlin", "Germany"],
    "罗马": ["罗马", "意大利", "Rome", "Italy"],
    "里斯本": ["里斯本", "葡萄牙", "Lisbon", "Portugal"],
    "雅典": ["雅典", "希腊", "Athens", "Greece"],
    "维也纳": ["维也纳", "奥地利", "Vienna", "Austria"],
    "苏黎世": ["苏黎世", "瑞士", "Zurich", "Switzerland"],
    "开罗": ["开罗", "埃及", "Cairo", "Egypt"],
    "突尼斯": ["突尼斯", "Tunis", "Tunisia"],
    "伊斯坦布尔": ["伊斯坦布尔", "土耳其", "Istanbul", "Turkey"],
    "墨西哥城": ["墨西哥", "Mexico City", "Mexico"],
    "圣保罗": ["圣保罗", "巴西", "Sao Paulo", "Brazil"],
    "纽约": ["纽约", "美国", "New York", "USA", "United States"],
}

# 国家码：城市 → ISO 国家（用于 fx 折算与国家维度）
_CITY_COUNTRY = {
    "香港": "HK", "新加坡": "SG", "迪拜": "AE", "伦敦": "GB",
    "雅加达": "ID", "曼谷": "TH", "吉隆坡": "MY", "东京": "JP", "首尔": "KR",
    "马尼拉": "PH", "胡志明市": "VN", "马德里": "ES", "巴黎": "FR", "柏林": "DE",
    "罗马": "IT", "里斯本": "PT", "雅典": "GR", "维也纳": "AT", "苏黎世": "CH",
    "开罗": "EG", "突尼斯": "TN", "伊斯坦布尔": "TR", "墨西哥城": "MX",
    "圣保罗": "BR", "纽约": "US",
}


def normalize_city(raw: str | None) -> tuple[str, str]:
    """返回 (标准城市名, 国家码)。未识别时返回 (原始串去空格, 'CN' 若含中文 else 'XX')。"""
    if not raw:
        return ("", "XX")
    t = raw.strip()
    for std, variants in _CITY_MAP.items():
        for v in variants:
            if v.lower() in t.lower():
                return (std, _CITY_COUNTRY.get(std, "CN"))
    # 未识别：含中文视为国内城市，保留原文
    if re.search(r"[一-鿿]", t):
        return (re.sub(r"(市|区|县)$", "", t), "CN")
    return (t, "XX")


# ---------- 经验归一化 ----------

_EXP = re.compile(r"(\d+)\s*[-–~]\s*(\d+)\s*年")
_EXP_MIN = re.compile(r"(\d+)\s*年以上|(\d+)\s*\+")
_EXP_FRESH = re.compile(r"应届|在校|经验不限|不限")


def normalize_experience(raw: str | None) -> tuple[float | None, float | None]:
    """'3-5年' → (3.0, 5.0)；'5年以上' → (5.0, None)；经验不限 → (None, None)。"""
    if not raw:
        return (None, None)
    t = raw.strip()
    if _EXP_FRESH.search(t):
        return (None, None)
    m = _EXP.search(t)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    m = _EXP_MIN.search(t)
    if m:
        v = m.group(1) or m.group(2)
        return (float(v), None)
    return (None, None)


# ---------- 学历归一化 ----------

_EDU_ORDER = ["博士", "硕士", "本科", "大专"]


def normalize_education(raw: str | None) -> str | None:
    if not raw:
        return None
    t = raw.strip()
    if re.search(r"不限|任何|无要求", t):
        return "不限"
    for e in _EDU_ORDER:
        if e in t:
            return e
    if "大专" in t or "专科" in t:
        return "大专"
    return None


# ---------- 岗位名归一 ----------

def normalize_position(raw: str) -> str:
    t = raw.strip().lower()
    t = re.sub(r"[（(【\[].*?[)）】\]]", "", t)  # 去括号备注
    t = re.sub(r"\s+", "", t)
    return t


# ---------- 岗位族关键词分类 ----------

_FAMILY_KEYWORDS = [
    ("tech", ["技术", "工程", "开发", "算法", "数据", "前端", "后端", "测试", "运维", "架构", "software", "engineer", "developer"]),
    ("product", ["产品", "product"]),
    ("supply_chain", ["供应链", "采购", "供应", "hotel", "contract", "bedbank", "采购经理"]),
    ("operations", ["运营", "操作", "op", "收益管理", "签证"]),
    ("marketing", ["市场", "品牌", "投放", "营销", "marketing", "growth"]),
    ("customer_service", ["客服", "客户服务", "售后"]),
    ("sales", ["销售", "商务拓展", "客户经理", "大客户", "渠道", "bd", "sales", "account"]),
    ("functional", ["法务", "律师", "法律", "人事", "人力", "财务", "会计", "行政", "hr", "合规"]),
]


def classify_job_family(position: str) -> str | None:
    """按岗位名关键词归类到岗位族 code，未命中返回 None。"""
    t = position.lower()
    for code, kws in _FAMILY_KEYWORDS:
        for kw in kws:
            if kw.lower() in t:
                return code
    return None


# ---------- 币种识别 ----------

_CURRENCY_SIGNS = [
    (re.compile(r"[¥￥]|人民币|RMB|CNY", re.I), "CNY"),
    (re.compile(r"S\$|SGD|新币|新加坡元", re.I), "SGD"),
    (re.compile(r"HKD|港币|港元|HK\$", re.I), "HKD"),
    (re.compile(r"AED|迪拉姆", re.I), "AED"),
    (re.compile(r"THB|泰铢|บาท", re.I), "THB"),
    (re.compile(r"IDR|印尼盾|Rp\b", re.I), "IDR"),
    (re.compile(r"MYR|林吉特|RM\b", re.I), "MYR"),
    (re.compile(r"JPY|日元|円|¥JP", re.I), "JPY"),
    (re.compile(r"KRW|韩元|원", re.I), "KRW"),
    (re.compile(r"PHP|比索", re.I), "PHP"),
    (re.compile(r"VND|越南盾", re.I), "VND"),
    (re.compile(r"₹|INR|卢比", re.I), "INR"),
    (re.compile(r"[€]|EUR|欧元", re.I), "EUR"),
    (re.compile(r"[£]|GBP|英镑", re.I), "GBP"),
    (re.compile(r"CHF|瑞士法郎", re.I), "CHF"),
    (re.compile(r"MXN|墨西哥比索", re.I), "MXN"),
    (re.compile(r"BRL|雷亚尔", re.I), "BRL"),
    (re.compile(r"EGP|埃及镑", re.I), "EGP"),
    (re.compile(r"TRY|里拉", re.I), "TRY"),
    (re.compile(r"TND|突尼斯第纳尔", re.I), "TND"),
    (re.compile(r"[$]|USD|美元|dollar", re.I), "USD"),
]


# 国家 → 默认币种（detect_currency 的兜底映射，覆盖 DIDA 海外驻地）
_COUNTRY_CURRENCY = {
    "CN": "CNY", "HK": "HKD", "SG": "SGD", "AE": "AED", "GB": "GBP",
    "ID": "IDR", "TH": "THB", "MY": "MYR", "JP": "JPY", "KR": "KRW",
    "PH": "PHP", "VN": "VND", "IN": "INR", "ES": "EUR", "FR": "EUR",
    "DE": "EUR", "IT": "EUR", "PT": "EUR", "GR": "EUR", "AT": "EUR",
    "CY": "EUR", "CH": "CHF", "EG": "EGP", "TN": "TND", "TR": "TRY",
    "MX": "MXN", "BR": "BRL", "US": "USD",
}


def detect_currency(raw: str | None, country: str = "CN") -> str:
    if raw:
        for pat, cur in _CURRENCY_SIGNS:
            if pat.search(raw):
                return cur
    return _COUNTRY_CURRENCY.get(country, "USD")


def dedup_hash(company_name: str, position_norm: str, city: str,
               monthly_low: float | None, monthly_high: float | None,
               collect_month: str) -> str:
    import hashlib
    key = "|".join([
        company_name.strip(), position_norm, city,
        f"{monthly_low}", f"{monthly_high}", collect_month,
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()
