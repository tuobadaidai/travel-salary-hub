"""stats_gov：国家统计局/人社局分行业平均工资导入器。

统计局数据是年度发布，形态为"人工下载 CSV → 归一导入"，不是网页爬虫。
CSV 口径：company_name(填 '国家统计局'), fiscal_year, report_type=gov_statistics,
avg_salary(元/年), source, source_url, confidence
继承 reports_csv 的导入逻辑（同表），仅注册独立 source_name 以便调度区分。
"""

from pipeline.collectors.reports_file import import_reports_csv

if __name__ == "__main__":
    import sys
    from pathlib import Path
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/seed/stats_gov_seed.csv")
    if not path.exists():
        print(f"no file: {path}")
        raise SystemExit(0)
    a, s = import_reports_csv(path)
    print(f"stats_gov: +{a}, skipped {s}")
