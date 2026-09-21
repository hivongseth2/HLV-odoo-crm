"""Gộp các bản ghi TRÙNG trong kho toạ độ.

Bản bị gộp KHÔNG bị xoá mà thành BÍ DANH trỏ về bản giữ lại. Vì sao: kho toạ độ tra theo
khoá chữ (``address_key``). Xoá bản trùng thì lần sau gặp đúng cách viết đó, ``resolve()``
không thấy gì trong kho và gọi Google lại — tốn tiền cho một địa chỉ đã biết, và có khi
ra một toạ độ khác với bản đã duyệt.

Việc CHỌN gộp gì nằm ở ``tools/vtracking_dedup`` (chỉ đề xuất). Ở đây chỉ gộp đúng các id
được chỉ định.
"""

from odoo import fields, models
from odoo.exceptions import UserError

from ..tools.vtracking_dedup import GEO_RANK

# Chuỗi bí danh dài quá mức này là dữ liệu vòng lặp hỏng, không phải chuỗi thật.
MAX_ALIAS_HOPS = 5


class HlvVtrackingAddressMerge(models.Model):
    _inherit = 'hlv.vtracking.address'

    alias_of_id = fields.Many2one(
        'hlv.vtracking.address', string='Đã gộp vào', index=True, ondelete='set null',
        readonly=True,
        help='Bản này là một cách viết khác của địa chỉ kia. Tra trúng bản này thì hệ thống '
             'dùng toạ độ của bản kia — giữ lại để khỏi phải tra lại cách viết này.',
    )

    def _canonical(self):
        """Bản gốc sau khi đi theo chuỗi bí danh. Chính nó nếu không phải bí danh."""
        self.ensure_one()
        record = self
        for _hop in range(MAX_ALIAS_HOPS):
            if not record.alias_of_id:
                return record
            record = record.alias_of_id
        return record

    def merge_into(self, keep):
        """Gộp ``self`` vào ``keep``. Trả về dict tóm tắt.

        - Bản giữ chưa có toạ độ mà bản gộp có -> lấy toạ độ đáng tin nhất trong các bản gộp.
        - Mọi dòng kế hoạch trỏ tới bản gộp chuyển sang bản giữ (giờ ước tính tự tính lại).
        - Bí danh cũ trỏ tới bản gộp chuyển sang trỏ thẳng bản giữ.
        - Số lần dùng lại cộng dồn vào bản giữ.
        """
        keep.ensure_one()
        duplicates = (self - keep).filtered(lambda record: record.company_id == keep.company_id)
        if not duplicates:
            raise UserError('Không có bản ghi nào để gộp vào địa chỉ #%s.' % keep.id)
        if keep.alias_of_id:
            raise UserError('Địa chỉ #%s đã là bí danh của #%s — gộp vào bản gốc.'
                            % (keep.id, keep.alias_of_id.id))

        if not keep.has_coords:
            donor = duplicates.filtered('has_coords').sorted(
                lambda record: GEO_RANK.get(record.geo_state, 9)
            )[:1]
            if donor:
                keep.write({
                    'latitude': donor.latitude, 'longitude': donor.longitude,
                    'geo_state': donor.geo_state, 'geo_source': donor.geo_source,
                })

        Line = self.env['hlv.vtracking.plan.line'].sudo()
        lines = Line.search([('address_id', 'in', duplicates.ids)])
        lines.write({'address_id': keep.id})
        self.search([('alias_of_id', 'in', duplicates.ids)]).write({'alias_of_id': keep.id})

        keep.write({
            'hit_count': keep.hit_count + sum(duplicates.mapped('hit_count')),
            'last_used_at': fields.Datetime.now(),
        })
        duplicates.write({'alias_of_id': keep.id})
        return {
            'keep_id': keep.id,
            'merged_ids': duplicates.ids,
            'plan_lines_moved': len(lines),
        }
