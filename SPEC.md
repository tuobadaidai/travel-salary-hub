# SPEC · travel-salary-hub v0.11 实施规格

来源：PRD v0.11（AD-1 ~ AD-5）。基线 commit `a5dc167`。

## S1 数据正确性修复（P0）

### S1.1 接通 fx_rates（PRD §8-1）

- `pipeline/ingest.py`：新增 `get_fx(cur: str) -> float` — 查 `fx_rates` 最新 `rate_date`，miss 时 fallback DEFAULT_FX 并打印告警。DEFAULT_FX 保留为 fallback 快照。
- `pipeline/clean_overseas.py:89,126`：`DEFAULT_FX.get(cur, …)` → `get_fx(cur)`。
- `pipeline/run_overseas.py` 同样替换（grep DEFAULT_FX 全部替换）。
- seed 已有 8 币种（fx_rates 表 9-15 日期），**补齐 21 币种**：seed_fx_rates 已幂等，重跑 init 时自动补 DEFAULT_FX 全表。
- 验证：IDR 记录 base 与手动算一致（±0.1%）；`fx_rates` 行数=21。

### S1.2 pay_hash 口径修正（PRD §8-2）

- `pipeline/import_dida_payroll.py:87` pay_hash 加入 currency、grade：`sha1(title|seq|grade|grade_equiv|monthly_cny|currency|location)`（monthly_cny 已是 CNY 折算值，currency 记原始币种做审计锚点）。
- 一次性迁移：删除旧 hash 全部重导（xlsx 源在 `~/.openclaw/workspace/`，重导入用同脚本）。
- 验证：重导入 added=704、skipped=0；再次重跑 added=0。

### S1.3 months>13 置信降级（PRD AD-4）

- `salary_records` 已有字段不加列；在 `stats.py` 各聚合处统一过滤：`months` 为 None 或 ≤13 计入，>13 标记 `low_conf=1` 且**不计入 P50**（记录数少，直接剔除并在响应 meta 注明剔除数）。
- 改动点：`quantiles_by_group`、`benchmark_matrix`、`benchmark_by_grade` 的查询处加 `.filter(or_(SalaryRecord.months.is_(None), SalaryRecord.months <= 13))`。
- 验证：法务总监前程无忧 P50 从 53.1万 → ~42万（离群 300万 剔除后）。

### S1.4 海外隔离（PRD AD-3）

- `benchmark_matrix` / `benchmark_by_grade` / `cross_heatmap` / `quantiles_by_group` 默认加 `SalaryRecord.country == 'CN'`（新增参数 `include_overseas=False`，显式开启才含）。
- 海外数据不删除，F6 视图用。

## S2 对标呈现重构（AD-1 / AD-5 核心）

### S2.1 后端 `benchmark_by_grade` 返回结构升级

响应新增 `cells` 结构（保留旧字段兼容一个版本）：

```jsonc
{
  "cells": {
    "P4": {                       // grade code
      "深圳": {
        "tier": 1,                // 1=本grade×本城市 2=本grade全国 3=级别带参照
        "dida": {count, p25, p50, p75, p90, reliable},
        "market_ref": {...} | null,   // tier2/3 时可能是全国参照
        "gap_pct": -0.082
      },
      "全国": {...}
    }
  },
  "market_band": {                // 级别带参照（pos×level 全国聚合）
    "主管": {count, p50, p75, ...},
    "经理": {...}
  },
  "national_reference": {...}     // 保留（report: 前缀）
}
```

tier 降级规则：grade×city 样本≥5 → tier1；否则 grade 全国样本≥5 → tier2；否则 market_band[等效level] → tier3；再无 → 无数据。
gap 仅在 tier1/tier2 且 market_ref.reliable 时计算。

### S2.2 DIDA 匹配两级收敛（AD-2）

- `stats.py` 新增 `dida_title_match(title_kw) -> list[title]`：
  1. 归一化关键词（剥离 资深/高级/技术/后台/智能 修饰词 → 基名）
  2. `didapay title LIKE %基名%` 取回全部 title 集合（如 产品经理 → [产品经理, 高级技术产品经理, 资深产品经理, 后台产品经理…]）
  3. SQL 改 `WHERE title IN (:titles)`，每行按其自身 grade 聚合（grade 是内部事实，不由 title 推断）
- `benchmark_by_grade` DIDA 查询从 `title = :kw` / `LIKE` 改用此函数。
- 验证：产品岗位 DIDA 样本从 10 条（精确 title）→ 26 条（族内）。

### S2.3 前端 Benchmark.vue 矩阵改造

- 每格渲染：tier1 显示 DIDA P50 + gap%；tier2 显示「全国 P50（城市差异见全国行）」灰字；tier3 只显示市场参照 P50；无数据显示「—」
- 矩阵下方固定一行「全国基准（Michael Page）」
- tier 用小角标（①②③）+ tooltip 解释降级原因
- 样本<5 的格子保留灰显（现有 reliable 逻辑）

## S3 海外驻地视图（F6）

- 后端：`/stats/overseas` — dida_payroll `location NOT IN (CN 城市清单)` 按 `location × level` 聚合（monthly_cny 已折算），返回国家、人数、P50、币种分布；市场侧 `salary_records country!='CN'` 单独返回（low 置信）。
- 前端：新增 `/overseas` 路由 + OverseasView.vue：国家卡片列表（人数/P50/CNY 折算区间），点击展开岗位明细。
- CN 城市清单放 `stats.py` 常量（深圳/长沙/上海/重庆/北京/成都/广州/杭州/南京/大连/潍坊/平湖 + 「全国」）。

## S4 调度器成功回调（PRD §8-5）

- `scheduler.py` `_trigger_job` 改用 `subprocess.run`（阻塞）包在线程里，结束后查最新 CollectRun（source_name 匹配）状态 success/partial → 写 `ingest_schedules.last_success_at`。
- 验证：手动触发后 schedules 表 last_success_at 非空。

## S5 前端 Skills 落地（frontend-design）

- Benchmark 矩阵 tier 视觉：tier1 实色卡、tier2/3 描边卡 + 灰字，保持现有深色侧栏风格
- 海外视图沿用现有 chip/card 语言，无新依赖

## S6 测试

- `tests/test_stats.py` 增补：S1.3 months 过滤、S2.2 dida_title_match、S2.1 tier 降级逻辑（构造内存 sqlite fixture）
- 全量 `pytest -q` 通过；`pnpm build` 通过

## 交付顺序

S1.1→S1.3→S1.4（后端过滤链）→ S2.1→S2.2（后端重构）→ S4 → S2.3+S5（前端）→ S3 → S6 → review
