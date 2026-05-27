# -*- coding: utf-8 -*-
import json

from odoo import fields, models, _
from odoo.exceptions import UserError

from ..services import shopee_product_api


class ShopeeProductOperationWizard(models.TransientModel):
    _name = 'shopee.product.operation.wizard'
    _description = 'Thao tác Shopee Product'

    shopee_product_id = fields.Many2one(
        'shopee.product',
        string='Sản phẩm Shopee',
        required=True,
        readonly=True,
    )
    operation = fields.Selection(
        [
            ('reply_comment', 'Trả lời bình luận'),
            ('size_chart_detail', 'Chi tiết bảng kích thước'),
            ('generate_kit_image', 'Tạo ảnh bộ sản phẩm'),
        ],
        string='Thao tác',
        required=True,
        readonly=True,
    )
    comment_id = fields.Char(string='Mã bình luận')
    reply_comment = fields.Text(string='Nội dung trả lời')
    size_chart_id = fields.Char(string='Mã bảng kích thước')
    component_list_json = fields.Text(
        string='Danh sách thành phần JSON',
        default='[]',
        help='VD: [{"component_item_id": 123, "component_model_id": 0}]',
    )

    def _credentials(self):
        return self.shopee_product_id._get_shopee_credentials()

    def _parse_positive_int(self, value, label):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise UserError(_('%s không hợp lệ.') % label)
        if parsed <= 0:
            raise UserError(_('%s phải lớn hơn 0.') % label)
        return parsed

    def _parse_component_list(self):
        try:
            component_list = json.loads(self.component_list_json or '[]')
        except Exception as exc:
            raise UserError(_('JSON thành phần không hợp lệ: %s') % str(exc))
        if not isinstance(component_list, list) or not component_list:
            raise UserError(_('Cần nhập ít nhất 1 thành phần để tạo ảnh bộ sản phẩm.'))
        if len(component_list) > 9:
            raise UserError(_('Shopee chỉ cho tối đa 9 thành phần.'))
        normalized = []
        for component in component_list:
            if not isinstance(component, dict):
                raise UserError(_('Mỗi thành phần phải là object JSON.'))
            item_id = self._parse_positive_int(
                component.get('component_item_id'), _('Mã sản phẩm thành phần')
            )
            item = {'component_item_id': item_id}
            model_id = component.get('component_model_id')
            if model_id not in (None, '', False):
                item['component_model_id'] = int(model_id)
            normalized.append(item)
        return normalized

    def action_execute(self):
        self.ensure_one()
        product = self.shopee_product_id
        creds = self._credentials()

        if self.operation == 'reply_comment':
            comment_id = self._parse_positive_int(self.comment_id, _('Mã bình luận'))
            reply = (self.reply_comment or '').strip()
            if not reply:
                raise UserError(_('Cần nhập nội dung trả lời.'))
            if len(reply) > 500:
                raise UserError(_('Nội dung trả lời tối đa 500 ký tự.'))
            result = shopee_product_api.call_reply_comment(
                creds, [{'comment_id': comment_id, 'comment': reply}]
            )
            return product._store_raw_section(
                'reply_comment_result',
                result,
                _('Đã gửi trả lời bình luận'),
                _('Kết quả trả lời đã được lưu vào Raw JSON.'),
            )

        if self.operation == 'size_chart_detail':
            size_chart_id = self._parse_positive_int(self.size_chart_id, _('Mã bảng kích thước'))
            result = shopee_product_api.call_get_size_chart_detail(creds, size_chart_id)
            return product._store_raw_section(
                'size_chart_detail', result, _('Đã lấy chi tiết bảng kích thước')
            )

        if self.operation == 'generate_kit_image':
            component_list = self._parse_component_list()
            result = shopee_product_api.call_generate_kit_image(creds, component_list)
            return product._store_raw_section(
                'generated_kit_image', result, _('Đã tạo ảnh bộ sản phẩm')
            )

        raise UserError(_('Thao tác không được hỗ trợ.'))
