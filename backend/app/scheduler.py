"""轻量调度器：后台线程，每天检查一次 ingest_schedules。

规则：
- 启动时自动初始化 ingest_schedules 表（把已知任务插进去）
- 每 24 小时检查一次：enabled=1 且距离 last_success_at > cadence 天数 → 自动触发
- 触发方式和手动触发一样（subprocess 跑）
- 失败不重试，等下一轮检查
"""
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.db import SessionLocal
from app.models import CollectRun, IngestSchedule

# 已知任务注册表：source_name → (触发函数名, cadence_days)
KNOWN_JOBS = {
    "jobui_companies": ("run_companies", 7),  # 每周跑一次
}

CHECK_INTERVAL_S = 24 * 3600  # 每天检查一次
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _ensure_schedules(db):
    """初始化 ingest_schedules 表。"""
    for name, (_, days) in KNOWN_JOBS.items():
        if not db.query(IngestSchedule).filter_by(source_name=name).first():
            db.add(IngestSchedule(
                source_name=name,
                cadence=f"every_{days}_days",
                enabled=1,
            ))
    db.commit()


def _trigger_job(name: str):
    """阻塞执行采集任务，成功后写 last_success_at（SPEC S4）。"""
    cmd_map = {
        "jobui_companies": ["python3", "-m", "pipeline.run_companies"],
    }
    cmd = cmd_map.get(name)
    if not cmd:
        return False
    started = datetime.now(timezone.utc)
    log_dir = PROJECT_ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{name}.log"
    timed_out = False
    with open(log_path, "a") as f:
        f.write(f"\n=== scheduler trigger {started.isoformat()} ===\n")
        f.flush()
        try:
            subprocess.run(cmd, cwd=str(PROJECT_ROOT / "backend"),
                           stdout=f, stderr=subprocess.STDOUT, check=False,
                           timeout=3 * 3600)
        except subprocess.TimeoutExpired:
            timed_out = True
            f.write(f"[scheduler] {name} TIMEOUT after 3h\n")
    if timed_out:
        return False
    # 只认触发之后新建的 CollectRun，避免旧 run 的 success 误标
    db = SessionLocal()
    try:
        run = (db.query(CollectRun)
               .filter_by(source_name=name)
               .filter(CollectRun.started_at >= started.isoformat(timespec="seconds"))
               .order_by(CollectRun.id.desc())
               .first())
        if run and run.status in ("success", "partial"):
            sched = db.query(IngestSchedule).filter_by(source_name=name).first()
            if sched:
                sched.last_success_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                db.commit()
            print(f"[scheduler] {name} ok (run #{run.id})")
            return True
        print(f"[scheduler] {name} finished with status={run.status if run else 'no-run'}")
        return False
    finally:
        db.close()


def scheduler_loop():
    """调度主循环。"""
    print("[scheduler] started")
    while True:
        try:
            db = SessionLocal()
            _ensure_schedules(db)
            now = datetime.now(timezone.utc)
            for sched in db.query(IngestSchedule).filter_by(enabled=1).all():
                try:
                    if sched.source_name not in KNOWN_JOBS:
                        continue
                    _, cadence_days = KNOWN_JOBS[sched.source_name]
                    last = sched.last_success_at or sched.last_run_at
                    if last:
                        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        if (now - last_dt).days < cadence_days:
                            continue
                    print(f"[scheduler] triggering {sched.source_name}")
                    _trigger_job(sched.source_name)
                    sched.last_run_at = now.isoformat(timespec="seconds")
                    db.commit()
                except Exception as e:
                    print(f"[scheduler] {sched.source_name} error: {e}")
        except Exception as e:
            print(f"[scheduler] error: {e}")
        finally:
            db.close()
        time.sleep(CHECK_INTERVAL_S)


def start_scheduler():
    """在 FastAPI startup 时调用。"""
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
