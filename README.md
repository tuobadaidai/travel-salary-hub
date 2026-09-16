# travel-salary-hub 旅行行业薪酬看板

面向旅行行业（OTA + B2B 平台）的企业内部薪酬对标看板。覆盖 19 家竞争公司 + DIDA 内部薪酬基准，多国家/币种折算，岗位×级别×区域三维对标。

## 三步跑起来

```bash
# 1. 后端
cd backend && pip install -r requirements.txt
cd .. && python3 backend/pipeline/ingest.py   # 建表 + 种子 + 历史 CSV 导入

# 2. 前端
cd frontend && pnpm install && pnpm build      # 产物 dist/ 由 FastAPI 托管

# 3. 起服务
cd backend && uvicorn app.main:app --port 8300
# 打开 http://localhost:8300 （API 文档 /docs）
```

开发模式：`scripts/dev.sh`（uvicorn --reload + vite dev server）。

## 核心功能

- **总览**：岗位族/公司类型分位数区间图 + 任意两维交叉透视热力图（点击格子穿透到原始记录证据链）
- **岗位对标**：选岗位 → 级别（专员→VP）× 城市（含海外驻地）矩阵，市场 P50 vs DIDA 内部 P50 + 差距百分比，点格穿透
- **公司名单**：19 家竞争公司详情 + 财报人均薪酬对照

## 数据采集（三通道引擎）

```bash
# 国内市场：DIDA 核心岗位 × 城市批量采集（jobui 聚合页，4s 限速）
python3 -m backend.pipeline.run_batch

# 海外市场：SearxNG 摘要抽取（Glassdoor/招聘站摘要级，搜索关键词可调）
python3 -m backend.pipeline.run_overseas

# DIDA 内部薪酬导入（匿名化，来源薪酬表 xlsx）
python3 -m backend.pipeline.import_dida_payroll [path.xlsx]

# 财报 CSV / 统计局 CSV 导入
python3 -m backend.pipeline.run_collector reports_csv data/seed/reports_seed.csv
```

通道：SearxNG(3004) 搜索发现 → scrapling(chrome指纹) 主抓 → Crawl4AI(11235) 备用；原始页面 JSONL 落盘 `data/raw/` 审计。

## 数据口径

- 薪酬统一折算 **CNY/年**（`annual_salary_avg_base`，汇率见 `fx_rates` 表，覆盖 20 币种）
- 分位数基于该折算字段；组内样本 <5 标记 `reliable=false`，前端置灰
- 级别体系：市场级 `level`（专员/高级/主管/经理/总监/VP）+ DIDA 职级 `dida_grade`（P0-P8/O1-O4/M4-M5，等效级映射见 `import_dida_payroll.py`）
- 财报人均薪酬（含社保/股权摊销）与 JD/聚合薪酬（现金口径）是两套口径，看板分开展示
- 海外摘要数据 `confidence=low`，extra_json 存来源清单

## 测试

```bash
cd backend && python3 -m pytest tests/ -q
```

## 结构

```
backend/  FastAPI + SQLAlchemy（app/）+ 采集清洗管线（pipeline/）
frontend/ Vue3 + ECharts + Element Plus
data/     salary.db + seed/ + raw/（采集审计 JSONL）
scripts/  dev.sh backup.sh
```
