# travel-salary-hub 旅行行业薪酬看板

面向旅行行业（OTA + B2B 平台）的企业内部薪酬对标看板。覆盖 19 家竞争公司，多国家/币种折算，就绪度波次更新。

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

## 数据更新

```bash
# 财报 CSV 导入（巨潮/披露易人工下载后填 data/seed/reports_seed.csv 口径）
python3 -m backend.pipeline.run_collector reports_csv data/seed/reports_seed.csv

# 统计局数据同理
python3 -m backend.pipeline.run_collector stats_gov data/seed/stats_gov_seed.csv

# 全部导入器幂等，可安全重跑
python3 backend/pipeline/ingest.py
```

JD 网页采集器框架已就绪（`pipeline/collectors/base.py`：限速/robots/无 Cookie/个人敏感字段硬拒绝），具体招聘网站采集器因合规评估未启用。

## 数据口径

- 薪酬统一折算 **CNY/年**（`annual_salary_avg_base`，汇率见 `fx_rates` 表）
- 分位数基于该折算字段；组内样本 <5 标记 `reliable=false`，前端置灰
- 财报人均薪酬（含社保/股权摊销）与 JD 薪酬（现金口径）是两套口径，看板分开展示

## 测试

```bash
cd backend && python3 -m pytest tests/ -q
```

## 结构

```
backend/  FastAPI + SQLAlchemy（app/）+ 采集清洗管线（pipeline/）
frontend/ Vue3 + ECharts + Element Plus
data/     salary.db + seed/（公司/岗位族/历史数据种子）
scripts/  dev.sh backup.sh
```
