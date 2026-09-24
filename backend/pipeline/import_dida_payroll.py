"""导入 DIDA 内部薪酬表（匿名化）为对标基准。

来源：.openclaw/workspace/薪酬表_已匹配国别系数_*.xlsx（多维表格导出）
只取分析所需字段，姓名/工号/法定姓名等个人标识不入库。
幂等：didapay_hash = sha1(职务|序列|职级|等效级|月薪CNY|地点)，重复跳过。

用法：
    python3 -m backend.pipeline.import_dida_payroll /path/to/薪酬表*.xlsx
"""

import glob
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.models import CollectRun  # noqa: E402

# DIDA 职级 → 等效级别（用于 level 维度，与市场"专员/高级/主管/经理/总监/VP"对齐）
GRADE_TO_LEVEL = {
    "O1": "专员", "O2": "专员", "O3": "高级", "O4": "主管",
    "P0": "专员", "P1": "专员", "P2": "高级", "P3": "高级",
    "P4": "主管", "P5": "经理", "P6": "经理", "P7": "总监",
    "P8": "总监", "P9": "VP",
    "M4": "总监", "M5": "VP",
}


def ensure_table():
    """直接用原始 SQL 建表（简单、独立于 ORM 元数据）。"""
    import sqlite3
    con = sqlite3.connect(str(PROJECT_ROOT / "data" / "salary.db"))
    con.execute("""
        CREATE TABLE IF NOT EXISTS dida_payroll (
            id INTEGER PRIMARY KEY,
            title TEXT,               -- 职务
            dept_l1 TEXT,             -- 一级部门
            seq TEXT,                 -- 序列 P/O/M
            grade TEXT,               -- 职级 P0-P8/O1-O4/M4-M5
            grade_equiv TEXT,         -- 等效国内职级（新）
            level TEXT,               -- 等效级别（专员/高级/主管/经理/总监/VP）
            monthly_cny REAL,         -- 月度总和 CNY
            annual_cny REAL,          -- 年化 = 月×12
            currency TEXT,
            location TEXT,            -- 工作地点
            pay_hash TEXT UNIQUE,     -- 匿名去重键
            imported_at TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_dp_title ON dida_payroll(title)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_dp_grade ON dida_payroll(grade)")
    con.commit()
    con.close()


def import_xlsx(path: str) -> tuple[int, int]:
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    idx = {h: i for i, h in enumerate(header)}

    import sqlite3
    con = sqlite3.connect(str(PROJECT_ROOT / "data" / "salary.db"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = skipped = 0
    for r in rows[1:]:
        def g(col):
            v = r[idx[col]] if col in idx else None
            return None if v in (None, "", "None", "#N/A") else str(v).strip()

        title = g("职务")
        monthly = r[idx.get("月度总和（CNY）", 999)]
        if not title or monthly in (None, "", "None"):
            continue
        monthly = float(monthly)
        seq = g("序列") or ""
        grade = g("职级") or g("等效国内职级（新）") or ""
        currency = g("币种") or "CNY"
        level = GRADE_TO_LEVEL.get(grade)
        loc = g("工作地点") or ""
        # hash 含 currency：原始币种变了（改薪/换驻地）视为新记录；monthly 已是 CNY 折算
        pay_hash = hashlib.sha1(
            "|".join([title, seq, grade, currency, f"{monthly:.2f}", loc]).encode()).hexdigest()
        exists = con.execute("SELECT 1 FROM dida_payroll WHERE pay_hash=?", (pay_hash,)).fetchone()
        if exists:
            skipped += 1
            continue
        con.execute(
            "INSERT INTO dida_payroll (title, dept_l1, seq, grade, grade_equiv, level, monthly_cny, "
            "annual_cny, currency, location, pay_hash, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (title, g("一级部门"), seq or None, grade or None, g("等效国内职级（新）"), level,
             monthly, monthly * 12, currency, loc, pay_hash, now))
        added += 1
    con.commit()
    con.close()
    return added, skipped


def main():
    paths = sys.argv[1:] or sorted(glob.glob(
        str(Path.home() / ".openclaw/workspace/薪酬表_已匹配国别系数_*新等效职级.xlsx")))
    if not paths:
        print("未找到薪酬表 xlsx，请传路径参数")
        return
    ensure_table()
    db = SessionLocal()
    run = CollectRun(source_name="dida_payroll_import", status="running",
                     params_json=str(paths[0]))
    db.add(run)
    db.commit()
    total_a = total_s = 0
    for p in paths:
        a, s = import_xlsx(p)
        total_a += a
        total_s += s
        print(f"{Path(p).name}: +{a} / dup {s}")
    run.items_fetched = total_a + total_s
    run.items_new = total_a
    run.status = "success"
    run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    print(f"done: +{total_a} rows")


if __name__ == "__main__":
    main()
