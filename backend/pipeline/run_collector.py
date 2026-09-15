"""采集/导入统一 CLI：python -m pipeline.run_collector <source> [args]

当前注册源：reports_csv（财报 CSV 导入）、stats_gov（统计局 CSV 导入）。
JD 网页采集器暂未启用（合规评估中），BaseCollector 框架已就绪。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.collectors.reports_file import import_reports_csv  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("usage: python -m pipeline.run_collector <reports_csv|stats_gov> [csv_path]")
        raise SystemExit(1)
    source = sys.argv[1]
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if source in ("reports_csv", "stats_gov"):
        if not path:
            print("csv path required")
            raise SystemExit(1)
        added, skipped = import_reports_csv(path)
        print(f"{source}: +{added}, skipped {skipped}")
    else:
        print(f"unknown source: {source}. JD web collectors not enabled (compliance review pending).")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
