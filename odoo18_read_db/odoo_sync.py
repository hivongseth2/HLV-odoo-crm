"""
odoo_sync.py — phần dùng chung của incremental_sync.py (mỗi 5 phút) và full_refresh.py (mỗi đêm):
đọc cấu hình, gọi Postgres của prd qua SSH, đưa cấu trúc bảng ở DB thô theo prd, chép dòng bằng COPY.

Chỉ chạm Postgres của prd bằng SELECT / COPY TO STDOUT — không qua worker Odoo, không ghi gì lên prd.
"""
import fcntl
import os
import re
import shlex
import subprocess
from datetime import datetime

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


def read_list(path):
    """Các dòng không trống của file, bỏ phần comment (# …). Trả list giữ thứ tự; file rỗng → []."""
    with open(path, encoding='utf-8') as fh:
        return [s for s in (line.split('#', 1)[0].strip() for line in fh) if s]


def read_secret_regex(path):
    """Regex tên cột bí mật: dòng không phải comment đầu tiên của file, không phân biệt hoa thường."""
    with open(path, encoding='utf-8') as fh:
        pattern = next(s for s in (line.strip() for line in fh) if s and not s.startswith('#'))
    return re.compile(pattern, re.IGNORECASE)


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def take_lock(work_dir, wait):
    """Khoá chung WORK_DIR/sync.lock (cùng khoá với load_backup.sh) để các lượt không chạy chồng.
    wait=True: chờ tới khi được; wait=False: đang bận thì trả None. Trả file đang giữ khoá."""
    lock = open(os.path.join(work_dir, 'sync.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
    except BlockingIOError:
        lock.close()
        return None
    return lock


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

    def now(self):
        """Giờ UTC trên prd — làm mốc đồng bộ, không phụ thuộc đồng hồ máy này."""
        return datetime.fromisoformat(self.rows("SELECT (now() AT TIME ZONE 'UTC')::timestamp")[0][0])

    def copy_out(self, query):
        """Chạy COPY (...) TO STDOUT trên prd, trả Popen để đọc stdout dạng CSV."""
        return subprocess.Popen(self._command(f"COPY ({query}) TO STDOUT (FORMAT csv)"),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def remote_columns(prd, tables=None):
    """{bảng: [(cột, kiểu SQL), ...]} theo thứ tự cột trên prd. tables=None → mọi bảng trong public;
    bảng không có trên prd thì vắng mặt."""
    only = ''
    if tables is not None:
        only = 'AND c.relname IN (' + ','.join("'" + t.replace("'", "''") + "'" for t in tables) + ')'
    result = {}
    for table, column, sqltype in prd.rows(f"""
            SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            WHERE c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped {only}
            ORDER BY c.relname, a.attnum"""):
        result.setdefault(table, []).append((column, sqltype))
    return result


def local_columns(cur, tables=None):
    """{bảng: {cột: nullable?}} của các bảng thật (không view) trong public của DB thô.
    tables=None → mọi bảng."""
    query = """
        SELECT c.table_name, c.column_name, c.is_nullable = 'YES'
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE'
        WHERE c.table_schema = 'public'"""
    if tables is None:
        cur.execute(query)
    else:
        cur.execute(query + " AND c.table_name = ANY(%s)", (list(tables),))
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


def create_table(cur, table, rcols):
    """Tạo ở DB thô một bảng prd mới có (sau deploy). Không ràng buộc nào ngoài khoá chính id — giống
    các bảng nạp từ backup — và cho claude_ro đọc như mọi bảng khác."""
    cur.execute(sql.SQL("CREATE TABLE {} ({})").format(
        sql.Identifier(table),
        sql.SQL(', ').join(sql.SQL("{} " + t).format(sql.Identifier(c)) for c, t in rcols)))
    if 'id' in dict(rcols):
        cur.execute(sql.SQL("ALTER TABLE {} ADD PRIMARY KEY (id)").format(sql.Identifier(table)))
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'claude_ro'")
    if cur.fetchone():
        cur.execute(sql.SQL("GRANT SELECT ON {} TO claude_ro").format(sql.Identifier(table)))
    log(f"  {table}: bảng mới trên prd — đã tạo")


def _copy_from_prd(conn, cur, prd, select, target, cols, timeout):
    """Đổ kết quả `select` (chạy trên prd) vào bảng `target` của DB thô, theo danh sách cột `cols`."""
    proc = prd.copy_out(select)
    cur.copy_expert(sql.SQL("COPY {} ({}) FROM STDIN (FORMAT csv)").format(
        sql.Identifier(target), sql.SQL(', ').join(map(sql.Identifier, cols))).as_string(conn),
        proc.stdout)
    if proc.wait(timeout=timeout) != 0:
        raise RuntimeError(f"COPY trên prd lỗi: {proc.stderr.read().decode(errors='replace').strip()}")


def upsert_changed(conn, prd, table, rcols, since):
    """Chép dòng có write_date >= since từ prd và upsert theo id. Trả số dòng đã upsert.
    Chưa commit — người gọi commit cùng với mốc đồng bộ."""
    cols = [c for c, _ in rcols]
    ident_cols = sql.SQL(', ').join(map(sql.Identifier, cols))
    select = sql.SQL("SELECT {} FROM {} WHERE write_date >= {}").format(
        ident_cols, sql.Identifier(table), sql.Literal(since)).as_string(conn)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE TEMP TABLE _inc ({}) ON COMMIT DROP").format(
            sql.SQL(', ').join(sql.SQL("{} " + t).format(sql.Identifier(c)) for c, t in rcols)))
        _copy_from_prd(conn, cur, prd, select, '_inc', cols, timeout=600)
        updates = sql.SQL(', ').join(
            sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c)) for c in cols if c != 'id')
        cur.execute(sql.SQL("INSERT INTO {} ({}) SELECT {} FROM _inc ON CONFLICT (id) DO UPDATE SET {}").format(
            sql.Identifier(table), ident_cols, ident_cols, updates))
        return cur.rowcount


def replace_all(conn, prd, table, rcols):
    """Xoá sạch bảng ở DB thô rồi chép lại toàn bộ dòng từ prd. Trả số dòng. Chưa commit — trong cùng
    giao dịch nên người đọc vẫn thấy bản cũ cho tới khi người gọi commit."""
    cols = [c for c, _ in rcols]
    select = sql.SQL("SELECT {} FROM {}").format(
        sql.SQL(', ').join(map(sql.Identifier, cols)), sql.Identifier(table)).as_string(conn)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE {}").format(sql.Identifier(table)))
        _copy_from_prd(conn, cur, prd, select, table, cols, timeout=1800)
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
        return cur.fetchone()[0]
