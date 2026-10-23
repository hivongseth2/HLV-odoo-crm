# -*- coding: utf-8 -*-
"""
scan_models_odoo_shell.py
=========================
Quét một bản SAO của DB Odoo (staging — KHÔNG chạy trên prod vì quét toàn bảng): model nào có dữ
liệu, model nào còn được ghi gần đây, field nào thật sự có giá trị. Dùng để chọn bảng/field đồng bộ
sang DB đọc riêng cho agent.

Chỉ đọc, không tạo bảng/schema (Odoo.sh chặn CREATE SCHEMA), không cần pg_stat_* (bị chặn quyền).
"Được dùng" đo bằng write_date/create_date; mốc là create_date mới nhất của mail_message
(≈ lúc staging sao chép prod).

Chạy: tab EDITOR của staging → Launcher → Notebook "Odoo-shell" → dán cả file vào một ô → Shift+Enter.
Ra: ~/scan_tables.csv, ~/scan_fields.csv (+ tóm tắt in ngay dưới ô).
"""
import csv
import os

from psycopg2 import sql

cr = env.cr
HOME = os.path.expanduser('~')

cr.execute("SELECT max(create_date) FROM mail_message")
ref = cr.fetchone()[0]
print(f"Mốc thời gian (≈ lúc sao chép prod): {ref}")

cr.execute("""
    SELECT c.oid, c.relname, m.id, m.model
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
    LEFT JOIN ir_model m ON replace(m.model, '.', '_') = c.relname
    WHERE c.relkind = 'r' AND m.transient IS NOT TRUE
    ORDER BY c.relname
""")
tables = cr.fetchall()

cr.execute("SELECT attrelid, array_agg(attname::text) FROM pg_attribute "
           "WHERE attnum > 0 AND NOT attisdropped GROUP BY attrelid")
columns = {oid: set(names) for oid, names in cr.fetchall()}

cr.execute("""
    SELECT f.model_id, f.name, f.ttype, f.relation, f.relation_table,
           f.field_description->>'en_US', string_agg(DISTINCT d.module, ',')
    FROM ir_model_fields f
    LEFT JOIN ir_model_data d ON d.model = 'ir.model.fields' AND d.res_id = f.id
    WHERE f.store AND f.ttype <> 'one2many'
    GROUP BY f.id
""")
fields_by_model = {}
for model_id, *info in cr.fetchall():
    fields_by_model.setdefault(model_id, []).append(info)

cr.execute("SELECT res_id, string_agg(DISTINCT module, ',') FROM ir_model_data "
           "WHERE model = 'ir.model' GROUP BY res_id")
model_modules = dict(cr.fetchall())


def activity_sql(table, cols):
    """Câu đếm dòng + hoạt động 7/30 ngày; cột write_date/create_date thiếu thì trả NULL."""
    wd, cd = 'write_date' in cols, 'create_date' in cols
    parts = [
        "count(*)",
        "max(write_date)" if wd else "NULL",
        "count(*) FILTER (WHERE write_date > %(ref)s - interval '7 days')" if wd else "NULL",
        "count(*) FILTER (WHERE write_date > %(ref)s - interval '30 days')" if wd else "NULL",
        "count(*) FILTER (WHERE create_date > %(ref)s - interval '30 days')" if cd else "NULL",
    ]
    return sql.SQL("SELECT " + ", ".join(parts) + " FROM {}").format(sql.Identifier(table))


table_rows = {}
table_out = []
for oid, table, model_id, model in tables:
    cols = columns.get(oid, set())
    cr.execute(activity_sql(table, cols), {'ref': ref})
    rows, last_write, w7, w30, c30 = cr.fetchone()
    table_rows[table] = rows
    cr.execute("SELECT pg_total_relation_size(%s)", (oid,))
    size = cr.fetchone()[0]
    table_out.append([table, model, model_modules.get(model_id), rows, size, last_write, w7, w30, c30])
    if rows > 100000:
        print(f"  {table}: {rows:,} dòng")

field_out = []
for oid, table, model_id, model in tables:
    rows = table_rows[table]
    if not model_id or not rows:
        continue
    cols = columns.get(oid, set())
    plain = [f for f in fields_by_model.get(model_id, []) if f[1] != 'many2many' and f[0] in cols]
    if plain:
        # Một lần quét bảng cho mọi cột: count(cột) = số ô có giá trị.
        query = sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(sql.SQL("count({})").format(sql.Identifier(f[0])) for f in plain),
            sql.Identifier(table))
        cr.execute(query)
        counts = cr.fetchone()
        for (name, ttype, relation, _rel_table, label, modules), non_null in zip(plain, counts):
            field_out.append([model, name, ttype, relation, label, modules, rows, non_null,
                              round(100.0 * non_null / rows, 1), None])
    for name, ttype, relation, rel_table, label, modules in fields_by_model.get(model_id, []):
        if ttype == 'many2many':
            field_out.append([model, name, ttype, relation, label, modules, rows, None, None,
                              table_rows.get(rel_table)])

with open(os.path.join(HOME, 'scan_tables.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['table', 'model', 'modules', 'rows', 'bytes', 'last_write', 'ghi_7d', 'ghi_30d', 'tao_30d'])
    w.writerows(sorted(table_out, key=lambda r: -r[3]))
with open(os.path.join(HOME, 'scan_fields.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['model', 'field', 'ttype', 'relation', 'label', 'modules', 'rows', 'non_null',
                'pct_co_du_lieu', 'm2m_rows'])
    w.writerows(sorted(field_out, key=lambda r: (-r[6], r[0], r[1])))

models = [t for t in table_out if t[1]]
print(f"\nModel có dữ liệu: {sum(1 for t in models if t[3])} | ghi trong 30 ngày: "
      f"{sum(1 for t in models if t[7])} | rỗng: {sum(1 for t in models if not t[3])}")
print("\n=== 60 MODEL GHI NHIỀU NHẤT 30 NGÀY: model | dòng | ghi 7d | ghi 30d | tạo 30d | ghi cuối ===")
for t in sorted((t for t in models if t[7]), key=lambda t: -t[7])[:60]:
    print(f"  {t[1]:<45} {t[3]:>9,} {t[6]:>8,} {t[7]:>8,} {t[8] or 0:>8,}  {t[5]:%Y-%m-%d}")
print(f"\nĐã ghi {HOME}/scan_tables.csv ({len(table_out)} bảng), {HOME}/scan_fields.csv ({len(field_out)} field)")
