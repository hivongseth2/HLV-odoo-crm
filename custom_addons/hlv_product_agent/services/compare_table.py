# -*- coding: utf-8 -*-
"""Bảng so sánh thông số (tool so_sanh_thong_so): Claude đưa dữ liệu, ở đây dựng HTML.

Không để Claude tự viết HTML như show_panel: bảng nào cũng cùng một kiểu, không lỗi trắng trang,
và mọi chữ lấy từ web đều được escape (bảng hiện trong iframe trên trang của sale).

Util thuần: vào dict / list, ra chuỗi. Không đụng ``self.env``.
"""
from html import escape

MIN_PRODUCTS = 2
MAX_PRODUCTS = 5
MAX_SPECS = 25
MAX_CELL_CHARS = 200
EMPTY_CELL = "—"

_STYLE = (
    "<style>"
    ".cmp th,.cmp td{text-align:center}"
    ".cmp td:first-child,.cmp th:first-child{text-align:left;background:#f6f8fb;font-weight:600;"
    "white-space:nowrap}"
    ".cmp th{min-width:130px}"
    ".cmp tr.diff td{background:#fff6d6}"
    ".cmp img{display:block;max-width:110px;max-height:90px;margin:0 auto 6px}"
    ".cmp .code{color:#5b6670;font-weight:400;font-size:12px}"
    ".cmp .price{color:#0d4c8c;font-weight:700}"
    ".cmp .note{display:inline-block;margin-top:3px;padding:1px 6px;border-radius:8px;"
    "background:#fff;color:#0d4c8c;font-size:11px;font-weight:600}"
    ".legend,.conclusion{margin:8px 0;color:#3e4c59}"
    ".legend span{background:#fff6d6;padding:0 6px}"
    "</style>"
)


def _text(value, limit=MAX_CELL_CHARS):
    return " ".join(str(value if value is not None else "").split())[:limit]


def _safe_url(url):
    """Link / ảnh dùng được trong bảng: chỉ http(s). Trả chuỗi rỗng nếu không hợp lệ."""
    url = _text(url, 500)
    return url if url.lower().startswith(("https://", "http://")) else ""


def _money(value):
    try:
        return "{:,.0f}đ".format(float(value)).replace(",", ".")
    except (TypeError, ValueError):
        return _text(value, 40)


def compare_table_problems(products, specs):
    """Lý do dữ liệu chưa dựng được bảng.

    Nhận: products = list dict (cần 'ten'), specs = list dict {'ten', 'gia_tri': list chuỗi}.
    Trả: list câu lỗi để Claude sửa rồi gọi lại. Biên: dữ liệu hợp lệ -> [].
    """
    problems = []
    if not isinstance(products, list) or not MIN_PRODUCTS <= len(products) <= MAX_PRODUCTS:
        problems.append("san_pham cần %s-%s mã." % (MIN_PRODUCTS, MAX_PRODUCTS))
        return problems
    if any(not isinstance(p, dict) or not _text(p.get("ten")) for p in products):
        problems.append("mỗi sản phẩm cần 'ten'.")
    if not isinstance(specs, list) or not 1 <= len(specs) <= MAX_SPECS:
        problems.append("thong_so cần 1-%s dòng." % MAX_SPECS)
        return problems
    for spec in specs:
        values = spec.get("gia_tri") if isinstance(spec, dict) else None
        if not isinstance(spec, dict) or not _text(spec.get("ten")):
            problems.append("mỗi dòng thông số cần 'ten'.")
        elif not isinstance(values, list) or len(values) != len(products):
            problems.append("dòng '%s' cần đúng %s giá trị (mỗi sản phẩm một, chưa biết thì '%s')."
                            % (_text(spec.get("ten"), 60), len(products), EMPTY_CELL))
    return problems


def _product_header(product):
    parts = []
    image = _safe_url(product.get("anh"))
    if image:
        parts.append('<img src="%s" alt="" referrerpolicy="no-referrer">' % escape(image))
    parts.append("<div>%s</div>" % escape(_text(product.get("ten"), 120)))
    if _text(product.get("ma")):
        parts.append('<div class="code">%s</div>' % escape(_text(product.get("ma"), 60)))
    if product.get("gia") not in (None, ""):
        parts.append('<div class="price">%s</div>' % escape(_money(product.get("gia"))))
    if product.get("ton") not in (None, ""):
        parts.append('<div class="code">Tồn: %s</div>' % escape(_text(product.get("ton"), 20)))
    if _text(product.get("ghi_chu")):
        parts.append('<span class="note">%s</span>' % escape(_text(product.get("ghi_chu"), 60)))
    return "<th>%s</th>" % "".join(parts)


def _spec_row(spec):
    values = [_text(value) or EMPTY_CELL for value in spec["gia_tri"]]
    known = {value.lower() for value in values if value != EMPTY_CELL}
    css = ' class="diff"' if len(known) > 1 else ""
    cells = "".join("<td>%s</td>" % escape(value) for value in values)
    return "<tr%s><td>%s</td>%s</tr>" % (css, escape(_text(spec["ten"], 80)), cells)


def compare_table_html(products, specs, conclusion=""):
    """HTML bảng so sánh (đã escape), gồm cả <style>; gọi sau khi compare_table_problems rỗng.

    Nhận: products, specs như compare_table_problems; conclusion: 1-2 câu kết luận (có thể rỗng).
    Trả: chuỗi HTML. Dòng mà các mã khác nhau được tô vàng; ô trống hiện EMPTY_CELL; dòng
    "Nguồn" chỉ có khi ít nhất một mã có link nguồn hợp lệ.
    """
    header = "<tr><th>Thông số</th>%s</tr>" % "".join(_product_header(p) for p in products)
    rows = [_spec_row(spec) for spec in specs]
    sources = [_safe_url(p.get("nguon")) for p in products]
    if any(sources):
        cells = "".join(
            '<td><a href="%s" target="_blank" rel="noopener noreferrer">Xem</a></td>' % escape(url)
            if url else "<td>%s</td>" % EMPTY_CELL for url in sources)
        rows.append("<tr><td>Nguồn</td>%s</tr>" % cells)
    parts = [_STYLE, '<table class="cmp">%s%s</table>' % (header, "".join(rows)),
             '<p class="legend"><span>Tô vàng</span> = các mã khác nhau ở thông số này.</p>']
    if _text(conclusion):
        parts.append('<p class="conclusion">%s</p>' % escape(_text(conclusion, 400)))
    return "".join(parts)
