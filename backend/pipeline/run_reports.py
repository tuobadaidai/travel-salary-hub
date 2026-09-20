"""上市公司年报人力成本采集：巨潮资讯年报 PDF → 支付给职工现金 + 员工数 → reports 表。

覆盖：竞争公司名单中已上市的 A股/港股公司（众信/凯撒/同程/携程/美团/途牛）。
口径：现金流量表「支付给职工以及为职工支付的现金」（含社保公积金，现金口径），
      与 JD 薪酬（现金总包）口径不同，看板分列。
人效指标 = 营收(亿元) / 员工数 → 人均营收；职工现金 / 员工数 → 人均人力成本。

用法：
    python3 -m backend.pipeline.run_reports                 # 全部上市公司
    python3 -m backend.pipeline.run_reports --company 众信旅游
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from pipeline.ingest import init_db, match_company  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CollectRun, Company, Report  # noqa: E402

CNINFO = "http://www.cninfo.com.cn"

# 已上市竞争公司 → 巨潮 (code, orgId)。orgId 用 topSearch/query 现查也可，静态缓存加快
LISTED = {
    "众信旅游": {"code": "002707", "exchange": "szse"},
    "凯撒旅业": {"code": "000796", "exchange": "szse"},
    "同程旅行": {"code": "00780", "exchange": "hk"},
    "携程集团": {"code": "09961", "exchange": "hk"},
    "美团": {"code": "03690", "exchange": "hk"},
    "途牛": {"code": "TOUR", "exchange": "nasdaq"},
}

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def cninfo_client() -> httpx.Client:
    s = httpx.Client(timeout=30, headers=UA, follow_redirects=True)
    s.get(f"{CNINFO}/new/index")
    return s


def resolve_org_id(s: httpx.Client, code: str, name: str) -> str | None:
    r = s.post(f"{CNINFO}/new/information/topSearch/query", data={"keyWord": name, "maxNum": 10})
    for item in r.json():
        if item.get("code") == code:
            return item.get("orgId")
    return None


def find_annual_report(s: httpx.Client, code: str, org_id: str, year: int) -> dict | None:
    """巨潮查年报 PDF。返回 {title, url, date}。"""
    r = s.post(f"{CNINFO}/new/hisAnnouncement/query", data={
        "pageNum": 1, "pageSize": 30, "column": "szse", "tabName": "fulltext",
        "stock": f"{code},{org_id}", "category": "category_ndbg_szsh",
        "seDate": f"{year + 1}-01-01~{year + 1}-12-31", "isHLtitle": "true",
    })
    for a in (r.json().get("announcements") or []):
        title = a.get("announcementTitle") or ""
        if "摘要" in title or "英文" in title or "已取消" in title:
            continue
        if re.match(rf"^{year}.*年度报告$", title):
            return {"title": title, "url": f"{CNINFO}/new/announcement/download?bulletinId=&announceTime={a.get('adjunctUrl','').split('/')[1]}&staticUrl={a.get('adjunctUrl')}",
                    "pdf": f"http://static.cninfo.com.cn/{a.get('adjunctUrl')}",
                    "date": a.get("announcementTime")}
    return None


def pdf_to_text(pdf_url: str, s: httpx.Client) -> str | None:
    try:
        data = s.get(pdf_url).content
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(data)
            path = f.name
        subprocess.run(["pdftotext", "-layout", "-q", path, path + ".txt"], check=True)
        return Path(path + ".txt").read_text(errors="ignore")
    except Exception as e:
        print(f"  PDF ERR {pdf_url[:60]}: {e}")
        return None
    finally:
        Path(path).unlink(missing_ok=True)
        Path(path + ".txt").unlink(missing_ok=True)


_RE_STAFF_CASH = re.compile(
    r"支付给职工[以以]及为职工支付的现金\s*([\d,]+\.\d{2})\s*([\d,]+\.\d{2})?")
_RE_STAFF_CASH2 = re.compile(
    r"支付给职工以及为职工支付的现金\s*\n?\s*([\d,]+\.\d{2})")
# 员工数：「报告期末在职员工的数量合计（人）\n 2,706」
_RE_EMP_TOTAL = re.compile(
    r"(?:在职员工的数量合计|在职员工[数数]量合计)\s*[（(]人[）)]\s*\n?\s*([\d,]+)")
_RE_EMP_TOTAL2 = re.compile(r"在职员工的数量合计[（(]人[）)][:：]?\s*([\d,]+)")
# 营业收入（利润表首行，单位：元）「营业收入\s*6,455,113,793.27\s*3,296,...」
_RE_REVENUE = re.compile(
    r"营业收入\s*([\d,]+\.\d{2})\s*([\d,]+\.\d{2})?")


def _to_num(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def parse_report_text(text: str) -> dict:
    """从年报文本提取 职工现金(当期) + 员工数合计 + 营业收入(当期)。"""
    out: dict = {}
    m = _RE_STAFF_CASH.search(text)
    if not m:
        m = _RE_STAFF_CASH2.search(text)
    if m:
        # 第一列是本期（巨潮年报现金流量表本期在左）
        out["staff_cash"] = _to_num(m.group(1))
        if m.group(2):
            out["staff_cash_prev"] = _to_num(m.group(2))
    m2 = _RE_EMP_TOTAL.search(text) or _RE_EMP_TOTAL2.search(text)
    if m2:
        out["employees"] = int(m2.group(1).replace(",", ""))
    m3 = _RE_REVENUE.search(text)
    if m3:
        out["revenue"] = _to_num(m3.group(1))
    return out


def upsert_report(db, run_id: int, company_name: str, fiscal_year: int, parsed: dict,
                  src_title: str, src_url: str) -> bool:
    """reports 表 upsert（company+year+type 幂等），返回是否更新。"""
    cid = match_company(db, company_name)
    if not cid:
        print(f"  SKIP {company_name}: 无公司匹配")
        return False
    existing = db.query(Report).filter_by(
        company_id=cid, fiscal_year=fiscal_year, report_type="annual_report").first()
    if not existing:
        existing = Report(company_id=cid, fiscal_year=fiscal_year, report_type="annual_report")
        db.add(existing)
    changed = False
    if parsed.get("staff_cash") and existing.total_comp != parsed["staff_cash"]:
        existing.total_comp = parsed["staff_cash"]  # 现金口径人力成本（元）
        changed = True
    if parsed.get("employees") and existing.employees != parsed["employees"]:
        existing.employees = parsed["employees"]
        changed = True
    if parsed.get("revenue") and existing.revenue != parsed["revenue"]:
        existing.revenue = parsed["revenue"]  # 营业收入（元）
        changed = True
    if changed:
        emp = existing.employees
        existing.avg_salary = round(existing.total_comp / emp) if (existing.total_comp and emp) else None
        existing.source = f"年报:{src_title[:40]}"
        existing.source_url = src_url
        existing.confidence = "high"
        existing.collect_run_id = run_id
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", nargs="*", help="指定公司名")
    ap.add_argument("--year", type=int, default=2024, help="财报年度")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    targets = {k: v for k, v in LISTED.items() if not args.company or k in args.company}
    run = CollectRun(source_name="annual_report_crawl", status="running",
                     params_json=json.dumps({"year": args.year, "companies": list(targets)},
                                            ensure_ascii=False))
    db.add(run)
    db.flush()

    s = cninfo_client()
    added = 0
    for name, meta in targets.items():
        if meta["exchange"] != "szse":
            # 港股/美股：巨潮无年报 PDF，用东财 F10 EMP_NUM + 营收（中置信）
            secucode = f"{meta['code']}.{'HK' if meta['exchange'] == 'hk' else 'US'}"
            emp = rev = None
            try:
                r = httpx.get(
                    "https://datacenter.eastmoney.com/securities/api/data/v1/get",
                    params={"reportName": "RPT_HKF10_INFO_ORGPROFILE", "columns": "ALL",
                            "filter": f"(SECUCODE=\"{secucode}\")",
                            "source": "HSF10", "client": "PC"},
                    headers=UA, timeout=15)
                d = r.json()
                emp = d["result"]["data"][0].get("EMP_NUM") if d.get("success") else None
            except Exception:
                pass
            try:
                r = httpx.get(
                    "https://datacenter.eastmoney.com/securities/api/data/v1/get",
                    params={"reportName": "RPT_HKF10_FN_MAININDICATOR", "columns": "ALL",
                            "filter": f"(SECUCODE=\"{secucode}\")(REPORT_DATE='{args.year}-12-31')",
                            "source": "HSF10", "client": "PC"},
                    headers=UA, timeout=15)
                d = r.json()
                if d.get("success") and d.get("result"):
                    rev = d["result"]["data"][0].get("OPERATE_INCOME")
            except Exception:
                pass
            if emp or rev:
                cid = match_company(db, name)
                if cid:
                    ex = db.query(Report).filter_by(
                        company_id=cid, fiscal_year=args.year, report_type="annual_report").first()
                    if not ex:
                        ex = Report(company_id=cid, fiscal_year=args.year, report_type="annual_report")
                        db.add(ex)
                    ch = False
                    if emp and ex.employees != emp:
                        ex.employees = emp
                        ch = True
                    if rev and ex.revenue != rev:
                        ex.revenue = rev
                        ch = True
                    if ch:
                        ex.source = f"东财F10({secucode})"
                        ex.confidence = "medium"
                        ex.collect_run_id = run.id
                        added += 1
                        eff = (rev / emp / 1e4) if (rev and emp) else None
                        print(f"  {name}: 员工 {emp} · 营收 {rev / 1e8 if rev else 0:.0f}亿 · 人均营收 {eff and f'{eff:.0f}万'}（F10，无薪酬总额）")
            else:
                print(f"  MISS {name}（{meta['exchange']}，员工数未取到）")
            continue

        org_id = resolve_org_id(s, meta["code"], name)
        if not org_id:
            print(f"  MISS {name}: orgId 未找到")
            continue
        ann = find_annual_report(s, meta["code"], org_id, args.year)
        if not ann:
            print(f"  MISS {name}: {args.year} 年报未找到")
            continue
        text = pdf_to_text(ann["pdf"], s)
        if not text:
            continue
        parsed = parse_report_text(text)
        if not parsed:
            print(f"  MISS {name}: 年报无职工现金/员工数字段")
            continue
        changed = upsert_report(db, run.id, name, args.year, parsed, ann["title"], ann["pdf"])
        added += 1 if changed else 0
        emp = parsed.get("employees")
        cash = parsed.get("staff_cash")
        rev = parsed.get("revenue")
        avg = round(cash / emp) if cash and emp else None
        eff = (rev / emp / 1e4) if (rev and emp) else None
        print(f"  {name}: 员工 {emp} · 职工现金 {cash / 1e8 if cash else 0:.1f}亿 · "
              f"营收 {rev / 1e8 if rev else 0:.1f}亿 · 人均人力成本 {avg and f'{avg/1e4:.1f}万'} · 人均营收 {eff and f'{eff:.0f}万'}")

    run.items_fetched = len(targets)
    run.items_new = added
    run.status = "success" if added else "partial"
    run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    print(f"done: {added} 家更新 → run #{run.id}")


if __name__ == "__main__":
    main()
