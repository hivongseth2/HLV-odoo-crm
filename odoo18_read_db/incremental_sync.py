#!/usr/bin/env python3
"""
incremental_sync.py — chép phần thay đổi của các bảng nóng (hot_tables.txt) từ prd sang RAW_DB.
Chạy mỗi 5 phút bằng cron. Cần RAW_DB đã được dựng bởi load_backup.sh.

Mỗi bảng: lấy dòng có write_date >= (mốc lần trước - OVERLAP_MINUTES) bằng COPY qua SSH, rồi upsert
theo id. Danh sách cột đọc lại từ prd mỗi lần: prd deploy thêm cột thì thêm cột vào DB thô, bỏ cột
thì cột đó đứng yên. Bảng thiếu ở một bên thì bỏ qua và ghi log — full_refresh.py đêm đó sẽ sửa.

Cột có tên khớp secret_columns.txt (token, password…) không chép — DB thô giữ chúng NULL.

Không bắt được: dòng bị xoá và thay đổi bằng SQL thô không cập nhật write_date — full_refresh.py bù.
"""
import os
import sys
import time
from datetime import timedelta

import psycopg2

from odoo_sync import (HERE, Prd, align_columns, load_env, local_columns, log, read_list,
                       read_secret_regex, remote_columns, take_lock, upsert_changed)


def main():
    cfg = load_env(os.path.join(HERE, 'raw_db.env'))
    tables = read_list(os.path.join(HERE, 'hot_tables.txt'))
    secret = read_secret_regex(os.path.join(HERE, 'secret_columns.txt'))
    overlap = timedelta(minutes=int(cfg.get('OVERLAP_MINUTES', '10')))

    lock = take_lock(cfg['WORK_DIR'], wait=False)
    if lock is None:
        log("Đang chép đêm hoặc lần trước chưa xong — bỏ lượt này.")
        return 0
    try:
        return sync(cfg, tables, secret, overlap)
    finally:
        lock.close()


def sync(cfg, tables, secret, overlap):
    started = time.monotonic()
    prd = Prd(cfg['SSH_TARGET'], cfg['REMOTE_DB'])
    conn = psycopg2.connect(dbname=cfg['RAW_DB'])
    # Mốc lấy trước khi đọc: lần sau đọc từ đây (trừ overlap).
    cycle_mark = prd.now()
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
            # Cột bí mật vẫn được tạo ở DB thô (align_columns) nhưng không bao giờ chép giá trị.
            n = upsert_changed(conn, prd, table, [(c, t) for c, t in rcols if not secret.search(c)], since)
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
