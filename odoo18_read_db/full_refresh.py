#!/usr/bin/env python3
"""
full_refresh.py — mỗi đêm chép lại mọi bảng của prd sang RAW_DB (DB đã dựng bằng load_backup.sh).

Không dùng pg_dump: pg_dump ≥ 16.4 đọc pg_settings lúc khởi động, mà tài khoản DB trên Odoo.sh không
được đọc view đó ("permission denied for view pg_settings"). COPY từng bảng chỉ cần quyền SELECT.

Mỗi bảng: TRUNCATE rồi COPY lại trong một giao dịch — người đọc thấy bản cũ cho tới khi bảng đó xong.
Bù những gì incremental_sync.py không bắt: dòng bị xoá, bảng ngoài hot_tables.txt, sửa bằng SQL thô
không đổi write_date, bảng nối nhiều-nhiều. Bảng mới trên prd được tạo ở DB thô; bảng prd đã bỏ thì
để nguyên và ghi log. Bảng khớp excluded_tables.txt bỏ qua; cột khớp secret_columns.txt không chép.

    full_refresh.py                      # mọi bảng (cron mỗi đêm)
    full_refresh.py stock_quant uom_uom  # chỉ các bảng nêu tên — để thử ban ngày mà không tải nặng prd
"""
import fnmatch
import os
import sys
import time

import psycopg2

from odoo_sync import (HERE, Prd, align_columns, create_table, load_env, local_columns, log,
                       read_list, read_secret_regex, remote_columns, replace_all, take_lock)


def main():
    cfg = load_env(os.path.join(HERE, 'raw_db.env'))
    excluded = read_list(os.path.join(HERE, 'excluded_tables.txt'))
    secret = read_secret_regex(os.path.join(HERE, 'secret_columns.txt'))

    only = sys.argv[1:] or None

    lock = take_lock(cfg['WORK_DIR'], wait=True)   # chờ lượt 5 phút đang chạy (nếu có) xong
    try:
        return refresh(cfg, excluded, secret, only)
    finally:
        lock.close()


def refresh(cfg, excluded, secret, only):
    started = time.monotonic()
    log(f"Bắt đầu chép lại {'toàn bộ' if only is None else ', '.join(only)} prd → {cfg['RAW_DB']}")
    prd = Prd(cfg['SSH_TARGET'], cfg['REMOTE_DB'])
    mark = prd.now()   # lấy trước khi chép: thay đổi trong lúc chép, lượt 5 phút sau sẽ lấy lại
    rcols_all = remote_columns(prd, only)
    conn = psycopg2.connect(dbname=cfg['RAW_DB'])
    with conn.cursor() as cur:
        lcols_all = local_columns(cur, only)
    conn.commit()

    tables = [t for t in sorted(rcols_all) if not any(fnmatch.fnmatchcase(t, p) for p in excluded)]
    total, failed = 0, []
    for table in tables:
        rcols = rcols_all[table]
        try:
            with conn.cursor() as cur:
                if table in lcols_all:
                    align_columns(cur, table, rcols, lcols_all[table])
                else:
                    create_table(cur, table, rcols)
            total += replace_all(conn, prd, table, [(c, t) for c, t in rcols if not secret.search(c)])
            conn.commit()
        except Exception as exc:  # noqa: BLE001 — một bảng lỗi không được chặn các bảng còn lại
            conn.rollback()
            failed.append(table)
            log(f"  {table}: LỖI {exc}")

    gone = sorted(set(lcols_all) - set(rcols_all))
    if gone:
        log(f"  {len(gone)} bảng không còn trên prd (để nguyên): {', '.join(gone[:15])}"
            + (' …' if len(gone) > 15 else ''))
    if only is None:   # mốc toàn DB chỉ đúng khi đã chép mọi bảng
        with conn.cursor() as cur:
            cur.execute("UPDATE sync.meta SET snapshot_at = %s", (mark,))
        conn.commit()
    conn.close()

    log(f"Xong {len(tables) - len(failed)}/{len(tables)} bảng, {total} dòng, mốc prd {mark} UTC, "
        f"{time.monotonic() - started:.0f}s" + (f" — lỗi: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
