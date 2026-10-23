#!/usr/bin/env python3
"""
incremental_sync.py — chép phần thay đổi của các bảng nóng (hot_tables.txt) từ prd sang RAW_DB.
Chạy mỗi 5 phút bằng cron. Cần RAW_DB đã được dựng bởi full_refresh.sh.

Mỗi bảng: lấy dòng có write_date >= (mốc lần trước - OVERLAP_MINUTES) bằng COPY qua SSH, rồi upsert
theo id. Chỉ chạm Postgres của prd, không qua worker Odoo.

Danh sách cột đọc lại từ prd mỗi lần, không cố định: prd deploy thêm cột thì thêm cột vào DB thô,
bỏ cột thì cột đó đứng yên ở DB thô. Bảng thiếu ở một bên thì bỏ qua và ghi log — bản chép đêm sẽ
đưa cấu trúc về khớp prd.

Không bắt được: dòng bị xoá (chép đêm dọn) và thay đổi bằng SQL thô không cập nhật write_date
(xem README).
"""
import fcntl
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta

import psycopg2
from psycopg2 import sql

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env(path):
    """Đọc file KEY=VALUE (dòng trống / bắt đầu bằng # bỏ qua). Trả dict; file thiếu → lỗi."""
    env = {}
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
    return env


def read_table_list(path):
    """Đọc danh sách tên bảng, mỗi dòng một bảng; bỏ dòng trống và comment. Trả list giữ thứ tự."""
    with open(path, encoding='utf-8') as fh:
        return [s for s in (line.split('#', 1)[0].strip() for line in fh) if s]


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


class Prd:
    """Gọi psql trên container prd qua SSH (login shell để có biến môi trường Postgres)."""

    def __init__(self, ssh_target, db):
        self.ssh_target = ssh_target
        self.db = db

    def _command(self, query, extra=''):
        inner = f"psql -X -At -v ON_ERROR_STOP=1 {extra} -d {shlex.quote(self.db)} -c {shlex.quote(query)}"
        return ['ssh', '-o', 'BatchMode=yes', self.ssh_target, 'bash -lc ' + shlex.quote(inner)]

    def rows(self, query):
        out = subprocess.run(self._command(query, "-F '|'"), capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise RuntimeError(f"prd psql lỗi: {out.stderr.strip()}")
        return [line.split('|') for line in out.stdout.splitlines() if line]

    def copy_out(self, query):
        """Chạy COPY (...) TO STDOUT trên prd, trả Popen để đọc stdout dạng CSV."""
        return subprocess.Popen(self._command(f"COPY ({query}) TO STDOUT (FORMAT csv)"),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def remote_columns(prd, tables):
    """{bảng: [(cột, kiểu SQL), ...]} theo thứ tự cột trên prd; bảng không có trên prd thì vắng mặt."""
    names = ','.join("'" + t.replace("'", "''") + "'" for t in tables)
    result = {}
    for table, column, sqltype in prd.rows(f"""
            SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            WHERE c.relname IN ({names}) AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY c.relname, a.attnum"""):
        result.setdefault(table, []).append((column, sqltype))
    return result


def local_columns(cur, tables):
    """{bảng: {cột: nullable?}} trên DB thô."""
    cur.execute("""
        SELECT table_name, column_name, is_nullable = 'YES'
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ANY(%s)""", (tables,))
    result = {}
    for table, column, nullable in cur.fetchall():
        result.setdefault(table, {})[column] = nullable
    return result


def align_columns(cur, table, rcols, lcols):
    """Đưa cấu trúc bảng thô theo prd: thêm cột mới; cột prd đã bỏ thì cho phép NULL để insert không vỡ."""
    for column, sqltype in rcols:
        if column not in lcols:
            cur.execute(sql.SQL("ALTER TABLE {} ADD COLUMN {} " + sqltype).format(
                sql.Identifier(table), sql.Identifier(column)))
            log(f"  {table}: thêm cột {column} {sqltype}")
    remote_names = {c for c, _ in rcols}
    for column, nullable in lcols.items():
        if column not in remote_names and not nullable:
            cur.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN {} DROP NOT NULL").format(
                sql.Identifier(table), sql.Identifier(column)))


def sync_table(conn, prd, table, rcols, since):
    """Chép dòng có write_date >= since từ prd và upsert theo id. Trả số dòng đã upsert."""
    cols = [c for c, _ in rcols]
    ident_cols = sql.SQL(', ').join(map(sql.Identifier, cols))
    select = sql.SQL("SELECT {} FROM {} WHERE write_date >= {}").format(
        ident_cols, sql.Identifier(table), sql.Literal(since)).as_string(conn)

    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE TEMP TABLE _inc ({}) ON COMMIT DROP").format(
            sql.SQL(', ').join(sql.SQL("{} " + t).format(sql.Identifier(c)) for c, t in rcols)))
        proc = prd.copy_out(select)
        cur.copy_expert(sql.SQL("COPY _inc ({}) FROM STDIN (FORMAT csv)").format(ident_cols).as_string(conn),
                        proc.stdout)
        if proc.wait(timeout=600) != 0:
            raise RuntimeError(f"COPY trên prd lỗi: {proc.stderr.read().decode(errors='replace').strip()}")
        updates = sql.SQL(', ').join(
            sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c)) for c in cols if c != 'id')
        cur.execute(sql.SQL("INSERT INTO {} ({}) SELECT {} FROM _inc ON CONFLICT (id) DO UPDATE SET {}").format(
            sql.Identifier(table), ident_cols, ident_cols, updates))
        return cur.rowcount


def main():
    cfg = load_env(os.path.join(HERE, 'raw_db.env'))
    tables = read_table_list(os.path.join(HERE, 'hot_tables.txt'))
    overlap = timedelta(minutes=int(cfg.get('OVERLAP_MINUTES', '10')))

    lock = open(os.path.join(cfg['WORK_DIR'], 'sync.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Đang chép đêm hoặc lần trước chưa xong — bỏ lượt này.")
        return 0

    started = time.monotonic()
    prd = Prd(cfg['SSH_TARGET'], cfg['REMOTE_DB'])
    conn = psycopg2.connect(dbname=cfg['RAW_DB'])
    # Mốc lấy trước khi đọc: lần sau đọc từ đây (trừ overlap), không phụ thuộc đồng hồ máy này.
    cycle_mark = datetime.fromisoformat(prd.rows("SELECT (now() AT TIME ZONE 'UTC')::timestamp")[0][0])
    rcols_all = remote_columns(prd, tables)

    with conn.cursor() as cur:
        lcols_all = local_columns(cur, tables)
        cur.execute("SELECT snapshot_at FROM sync.meta")
        snapshot_at = cur.fetchone()[0]
        cur.execute("SELECT table_name, mark FROM sync.state")
        marks = dict(cur.fetchall())
    conn.commit()

    total, failed = 0, []
    for table in tables:
        rcols, lcols = rcols_all.get(table), lcols_all.get(table)
        if not rcols:
            log(f"  {table}: không có trên prd — bỏ qua")
            continue
        if not lcols:
            log(f"  {table}: chưa có ở DB thô — chờ lần chép đêm")
            continue
        if 'write_date' not in dict(rcols):
            log(f"  {table}: không có write_date — chỉ mới theo lần chép đêm")
            continue
        since = marks.get(table, snapshot_at) - overlap
        try:
            with conn.cursor() as cur:
                align_columns(cur, table, rcols, lcols)
            n = sync_table(conn, prd, table, rcols, since)
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sync.state (table_name, mark, rows_last, synced_at) VALUES (%s, %s, %s, now())
                    ON CONFLICT (table_name) DO UPDATE
                    SET mark = EXCLUDED.mark, rows_last = EXCLUDED.rows_last, synced_at = EXCLUDED.synced_at""",
                            (table, cycle_mark, n))
            conn.commit()
            total += n
        except Exception as exc:  # noqa: BLE001 — một bảng lỗi không được chặn các bảng còn lại
            conn.rollback()
            failed.append(table)
            log(f"  {table}: LỖI {exc}")

    conn.close()
    log(f"Xong {len(tables) - len(failed)}/{len(tables)} bảng, {total} dòng, "
        f"{time.monotonic() - started:.1f}s" + (f" — lỗi: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
