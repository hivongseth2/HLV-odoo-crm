# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError
from ..utils.jt_api_utils import JTApiUtils
import logging

_logger = logging.getLogger(__name__)

class JTCreateOrderWizard(models.TransientModel):
    _name = "jt.create.order.wizard"
    _description = "J&T Create Order Wizard"

    picking_id = fields.Many2one('stock.picking', string="Picking", required=True)
    
    # J&T Specific Fields
    order_type = fields.Selection([
        ('1', 'Đơn bình thường'),
        ('2', 'Đơn chuyển hoàn')
    ], string="Loại đơn đặt", default='1', required=True)
    
    service_type = fields.Selection([
        ('1', 'Pickup'),
        ('6', 'Drop off')
    ], string="Loại dịch vụ", default='1', required=True)
    
    pay_type = fields.Selection([
        ('PP_PM', 'Thanh toán cuối tháng'),
        ('PP_CASH', 'Người gửi thanh toán'),
        ('CC_CASH', 'Người nhận thanh toán')
    ], string="Phương thức thanh toán", default='PP_PM', required=True)
    
    product_type = fields.Selection([
        ('EXPRESS', 'EXPRESS'),
        ('FAST', 'FAST'),
        ('SUPER', 'SUPER')
    ], string="Loại hàng hóa (Dịch vụ)", default='EXPRESS', required=True)
    
    goods_type = fields.Selection([
        ('bm000001', 'Document (bm000001)'),
        ('bm000010', 'Goods (bm000010)'),
        ('bm000011', 'Fresh (bm000011)')
    ], string="Mã loại hàng hóa", default='bm000010', required=True)

    delivery_type = fields.Selection([
        ('1', 'Phát bình thường'),
        ('2', 'Khách hàng tự đến lấy')
    ], string="Loại phát hàng", default='1', required=True)

    is_insured = fields.Boolean(string="Khai giá?", default=False)
    goods_value = fields.Float(string="Giá trị hàng hóa (VND)")
    cod_money = fields.Float(string="Tiền thu hộ (COD)")
    remark = fields.Text(string="Ghi chú")

    # Weight and Dimensions
    weight = fields.Float(string="Trọng lượng (kg)", default=0.1)
    length = fields.Float(string="Dài (cm)", default=10)
    width = fields.Float(string="Rộng (cm)", default=10)
    height = fields.Float(string="Cao (cm)", default=10)

    @api.model
    def default_get(self, fields):
        res = super(JTCreateOrderWizard, self).default_get(fields)
        if self._context.get('active_id'):
            picking = self.env['stock.picking'].browse(self._context.get('active_id'))
            res.update({
                'picking_id': picking.id,
                'cod_money': picking.sale_id.amount_total if picking.sale_id else 0.0,
                'goods_value': picking.sale_id.amount_total if picking.sale_id else 0.0,
            })
            # Try to get weight from picking/move lines if possible
            total_weight = sum(move.product_id.weight * move.product_uom_qty for move in picking.move_ids)
            if total_weight > 0:
                res['weight'] = total_weight
        return res

    def action_create_jt_order(self):
        self.ensure_one()
        company = self.picking_id.company_id
        get_param = self.env['ir.config_parameter'].sudo().get_param
        api_account = get_param('jnt_apiAccount')
        private_key = get_param('jnt_privateKey')

        if not api_account or not private_key:
            raise UserError(_("Thiếu jnt_apiAccount hoặc jnt_privateKey trong System Parameters!"))

        client = JTApiUtils(
            api_account=api_account,
            private_key=private_key,
            environment=company.jt_environment
        )

        # Prepare Sender Info (from current company/warehouse)
        warehouse = self.picking_id.picking_type_id.warehouse_id
        sender_partner = warehouse.partner_id or company.partner_id
        
        # Prepare Receiver Info
        receiver_partner = self.picking_id.partner_id
        if not receiver_partner:
            raise UserError(_("Vui lòng chọn khách hàng cho Phiếu xuất kho này."))

        # J&T requires prov, city, area. Odoo has state_id, city, and maybe street2 as area.
        # This will need mapping if the address structure is different.
        # For now, let's use the partner fields.
        
        biz_params = {
            "customerCode": company.jt_customer_code or "",
            "password": company.jt_password or "",
            "txlogisticId": self.picking_id.name,
            "orderType": int(self.order_type),
            "serviceType": int(self.service_type),
            "deliveryType": int(self.delivery_type),
            "selfAddress": 0, # Use J&T addresses or administrative? Documentation says 0 for J&T
            "payType": self.pay_type,
            "productType": self.product_type,
            "goodsType": self.goods_type,
            "sender": {
                "name": sender_partner.name,
                "mobile": sender_partner.mobile or sender_partner.phone or "",
                "prov": sender_partner.state_id.name or "",
                "city": sender_partner.city or "",
                "area": sender_partner.street2 or "", # Often used for ward/area in VN Odoo
                "address": sender_partner.street or ""
            },
            "receiver": {
                "name": receiver_partner.name,
                "mobile": receiver_partner.mobile or receiver_partner.phone or "",
                "prov": receiver_partner.state_id.name or "",
                "city": receiver_partner.city or "",
                "area": receiver_partner.street2 or "",
                "address": receiver_partner.street or ""
            },
            "packageInfo": {
                "weight": str(self.weight),
                "length": int(self.length),
                "width": int(self.width),
                "height": int(self.height),
            },
            "isInsured": 1 if self.is_insured else 0,
            "goodsValue": str(self.goods_value),
            "codMoney": str(self.cod_money) if self.pay_type == 'CC_CASH' or self.cod_money > 0 else "0",
            "remark": self.remark or "",
            "items": []
        }

        # Add items
        for move in self.picking_id.move_ids:
            biz_params["items"].append({
                "itemName": move.product_id.name[:80],
                "englishName": move.product_id.name[:80], # J&T requires englishName
                "number": str(int(move.product_uom_qty)),
                "itemValue": str(move.product_id.list_price)
            })

        _logger.info("J&T Creating Order for %s", self.picking_id.name)
        result = client.add_order(biz_params)

        if result.get('code') == '1':
            data = result.get('data', {})
            self.picking_id.write({
                'jt_bill_code': data.get('billCode'),
                'jt_sort_line': data.get('sortLine'),
                'jt_cod_fee': data.get('codFee', 0.0),
                'jt_insurance_fee': data.get('insuranceFee', 0.0),
                'jt_total_fee': data.get('inquiryFee', 0.0),
                'jt_order_status': 'Created'
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thành công',
                    'message': f'Đã tạo đơn J&T thành công! Mã vận đơn: {data.get("billCode")}',
                    'type': 'success',
                }
            }
        else:
            raise UserError(_("Lỗi từ J&T: %s") % result.get('msg', 'Unknown Error'))
