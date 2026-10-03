# -*- coding: utf-8 -*-
"""
check_chatgpt_category_names.py
===============================
Soát tên nhóm hàng trong tài liệu phân nhóm của trợ lý AI so với tên THẬT trên MISA.

Vì sao cần: trợ lý đọc tên nhóm từ tài liệu rồi gọi search_category_misa theo đúng tên
đó. Tên trong tài liệu lệch tên trên MISA là tra không ra, trợ lý kết luận "không tìm
thấy nhóm" rồi bỏ dở việc tạo mã. Đã gặp thật: tài liệu ghi "Bulong máy", MISA lưu
"Bu lông máy" — thiếu dấu cách và dấu mũ là trượt.

Khớp lỏng (bỏ dấu, bỏ khoảng trắng) đã được thêm vào _get_category_id_by_name nên các ca
lệch nhẹ không còn làm hỏng việc. Script này để dọn nốt cho tài liệu đúng hẳn, và để bắt
các ca lệch NẶNG mà khớp lỏng cũng không cứu được (đổi tên nhóm, nhóm đã xoá).

Đối chiếu theo ID chứ không theo tên: ID là khoá ổn định, tên mới là thứ hay bị sửa.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc), không đổi gì bên MISA.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_chatgpt_category_names.py
"""

import io
import os
import re

from odoo.modules.module import get_module_path

# ---- Sửa ở đây -----------------------------------------------------------------------------
DOC_PATH = ''      # để trống = tự tìm trong hlv_product_agent/data/prompt_defaults/
# ---------------------------------------------------------------------------------------------

SEP = "=" * 100
# Dòng bảng dạng: | Bu lông máy | `BULONGMAY` | 257 |
ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|")

misa = env['misa.api.utils'].sudo()

# Không raise bên trong except: exception lồng nhau làm trình in traceback của IPython
# sập ("'tuple' object has no attribute 'tb_frame'"), nuốt mất thông báo thật.
normalize_vn = None
import_error = ''
try:
    from odoo.addons.misa_fetch_po_button.utils.text_match import normalize_vn
except ImportError as error:
    import_error = str(error)

if normalize_vn is None:
    print(f"\n  ⚠️  Không nạp được utils/text_match.py của misa_fetch_po_button: {import_error}")
    print("      Server chưa có code mới (chưa pull/build) hoặc chưa restart Odoo.")
    print("      Vẫn soát được, nhưng không tách được 'lệch nhẹ' với 'lệch nặng' —")
    print("      mọi tên khác nhau sẽ xếp chung vào LỆCH NẶNG.\n")


def doc_path():
    """Đường dẫn tài liệu phân nhóm. Trả '' nếu không tự tìm được."""
    if DOC_PATH:
        return DOC_PATH
    base = get_module_path('hlv_product_agent')
    if not base:
        return ''
    return os.path.join(base, 'data', 'prompt_defaults', 'product_category_rules.md')


path = doc_path()
if not path or not os.path.exists(path):
    raise SystemExit("Không thấy tài liệu phân nhóm (%s). Điền DOC_PATH ở đầu script."
                     % (path or 'hlv_product_agent chưa cài'))

rows = []
for line in io.open(path, encoding='utf-8'):
    found = ROW_RE.match(line.strip())
    if found and found.group(3).isdigit():
        rows.append({'name': found.group(1).strip(), 'code': found.group(2).strip(),
                     'id': found.group(3).strip()})

print(f"\n{SEP}\n  SOÁT TÊN NHÓM HÀNG — tài liệu AI vs MISA\n  {path}\n{SEP}")
print(f"  Đọc được {len(rows)} nhóm trong tài liệu. Đang hỏi MISA từng ID...\n")

headers = misa._get_cached_crm_headers()
buckets = {'khop': [], 'lech_nhe': [], 'lech_nang': [], 'khong_thay': [], 'loi': []}

for row in rows:
    try:
        real = misa._get_category_name_by_id(headers, row['id'])
    except Exception as error:
        row['note'] = f"{type(error).__name__}: {error}"
        buckets['loi'].append(row)
        continue

    row['real'] = (real or '').strip()
    if not row['real']:
        buckets['khong_thay'].append(row)
    elif row['real'] == row['name']:
        buckets['khop'].append(row)
    elif normalize_vn and normalize_vn(row['real']) == normalize_vn(row['name']):
        buckets['lech_nhe'].append(row)
    else:
        buckets['lech_nang'].append(row)

LABEL = {
    'khop': "KHỚP ĐÚNG — không phải sửa gì",
    'lech_nhe': "LỆCH NHẸ (dấu / khoảng trắng) — khớp lỏng vẫn cứu được, nên sửa tài liệu cho sạch",
    'lech_nang': "LỆCH NẶNG — tên khác hẳn, AI tra KHÔNG RA, phải sửa tài liệu",
    'khong_thay': "MISA KHÔNG CÓ ID NÀY — nhóm đã xoá/đổi, phải bỏ hoặc thay trong tài liệu",
    'loi': "LỖI GỌI MISA — chạy lại sau",
}

for key in ('lech_nang', 'khong_thay', 'lech_nhe', 'loi', 'khop'):
    items = buckets[key]
    if not items:
        continue
    print(f"\n{SEP}\n  {LABEL[key]}: {len(items)} nhóm\n{SEP}")
    if key == 'khop':
        print("  " + ", ".join(sorted(item['code'] for item in items)))
        continue
    for item in items:
        if key == 'loi':
            print(f"  ▸ {item['code']:<24} ID {item['id']:<6} {item['note']}")
        elif key == 'khong_thay':
            print(f"  ▸ {item['code']:<24} ID {item['id']:<6} tài liệu ghi {item['name']!r}")
        else:
            print(f"  ▸ {item['code']:<24} ID {item['id']:<6}\n"
                  f"      tài liệu : {item['name']!r}\n"
                  f"      MISA     : {item['real']!r}")

print(f"\n{SEP}\n  TỔNG KẾT\n{SEP}")
for key in ('khop', 'lech_nhe', 'lech_nang', 'khong_thay', 'loi'):
    print(f"  {LABEL[key]:<78} {len(buckets[key]):>4}")
need_fix = buckets['lech_nhe'] + buckets['lech_nang'] + buckets['khong_thay']
if need_fix:
    print("\n  Sửa tài liệu product_category_rules.md: lấy cột 'MISA' làm chuẩn, thay vào cột tên.")
    print("  Sửa xong nhớ nạp lại file lên vector store (bản cũ phải xoá, không thì hai nguồn đá nhau).")
else:
    print("\n  Tài liệu khớp MISA hoàn toàn.")
print(SEP)
