#!/bin/bash
# 备份 SQLite 数据库（WAL checkpoint 后拷贝）
cd "$(dirname "$0")/.." || exit 1
mkdir -p data/exports
ts=$(date +%Y%m%d_%H%M%S)
sqlite3 data/salary.db "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || python3 -c "
import sqlite3
sqlite3.connect('data/salary.db').execute('PRAGMA wal_checkpoint(TRUNCATE)')
"
cp data/salary.db "data/exports/backup_${ts}.db"
echo "backup: data/exports/backup_${ts}.db"
