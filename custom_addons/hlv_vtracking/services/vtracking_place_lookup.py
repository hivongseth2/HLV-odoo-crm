"""Tra ĐỊA ĐIỂM theo khách — một chỗ duy nhất cho mọi nơi cần.

Vì sao phải có file riêng: ghép khách với địa điểm có hai bẫy chồng lên nhau.

1. Mỗi khách có nhiều **liên hệ con** làm địa chỉ giao → phải quy về ``commercial_partner_id``.
2. Cùng một công ty lại nằm ở nhiều **mã khách gốc** khác nhau trong Odoo (đo 22/09/2026:
   Summit Polymers là #132 và #21366, Dongjin là #133 và #18188, Chosun là #611 và #1058).
   ``commercial_partner_id`` gom được bẫy 1 nhưng không gom được bẫy 2 — hai bản ghi công ty
   trùng nhau thì mỗi bản là gốc của chính nó. Chỗ vá là ô ``alias_partner_ids`` trên địa
   điểm: khai mã phụ ở đó thì phiếu ghi mã nào cũng về đúng một điểm.

Hệ quả nếu tra sai: phiếu không có điểm → không có cụm → không học được định mức và không
treo được thói quen khách. Đo trên nhật ký quét: 50% lần giao rơi vào cảnh đó.
"""


def root_place_domain(root_ids, company):
    """Domain tìm địa điểm của các pháp nhân gốc ``root_ids`` trong ``company``."""
    return [
        ('company_id', '=', company.id),
        '|',
        ('partner_id.commercial_partner_id', 'in', list(root_ids)),
        ('alias_partner_ids.commercial_partner_id', 'in', list(root_ids)),
    ]


def places_by_root_partner(env, company, roots=None):
    """``{id pháp nhân gốc: địa điểm}`` — kể cả mã phụ.

    ``roots`` là recordset hoặc danh sách id để giới hạn truy vấn; bỏ trống thì lấy hết địa
    điểm của công ty. Một pháp nhân khai ở nhiều điểm thì ưu tiên điểm ĐÃ gán cụm, sau đó
    lấy id nhỏ nhất — để hai lần gọi cùng dữ liệu cho cùng kết quả.
    """
    Place = env['hlv.vtracking.place'].sudo()
    if roots is None:
        places = Place.search([('company_id', '=', company.id)], order='id asc')
    else:
        root_ids = roots.ids if hasattr(roots, 'ids') else list(roots)
        if not root_ids:
            return {}
        places = Place.search(root_place_domain(root_ids, company), order='id asc')

    result = {}
    for place in places.sorted(lambda place: (not place.zone_id, place.id)):
        for partner in place.partner_id | place.alias_partner_ids:
            result.setdefault(partner.commercial_partner_id.id, place)
    return result


def place_for_partner(env, company, partner):
    """Địa điểm của một khách — recordset rỗng nếu chưa khai."""
    root = partner.commercial_partner_id
    if not root:
        return env['hlv.vtracking.place'].browse()
    return env['hlv.vtracking.place'].sudo().search(
        root_place_domain([root.id], company), order='id asc', limit=1,
    )
