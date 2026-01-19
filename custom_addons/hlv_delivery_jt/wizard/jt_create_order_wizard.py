# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError
from ..utils.jt_api_utils import JTApiUtils
import hashlib
import logging

_logger = logging.getLogger(__name__)

class JTCreateOrderWizard(models.TransientModel):
    _name = "jt.create.order.wizard"
    _description = "J&T Create Order Wizard"

    picking_id = fields.Many2one('stock.picking', string="Picking", required=True)
    warehouse_id = fields.Many2one('stock.warehouse', string="Kho hàng", related='picking_id.picking_type_id.warehouse_id', readonly=True)
    
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
        ('bm000001', 'Tài liệu (bm000001)'),
        ('bm000010', 'Hàng hóa (bm000010)'),
        ('bm000011', 'Đồ tươi sống (bm000011)')
    ], string="Loại hàng hóa", default='bm000010', required=True)

    delivery_type = fields.Selection([
        ('1', 'Phát bình thường'),
        ('2', 'Khách hàng tự đến lấy')
    ], string="Loại phát hàng", default='1', required=True)

    is_insured = fields.Boolean(string="Khai giá?", default=False)
    goods_value = fields.Float(string="Giá trị hàng hóa (VND)")
    cod_money = fields.Float(string="Tiền thu hộ (COD)")
    remark = fields.Text(string="Ghi chú")

    part_sign = fields.Boolean(string="Ký nhận một phần?", help="0: ký nhận toàn phần, 1: ký nhận một phần")

    # Note Checkboxes
    note_thu_hang = fields.Boolean(string="Cho khách thử hàng")
    note_xem_hang_khong_thu = fields.Boolean(string="Cho khách xem hàng, không cho thử")
    note_de_vo = fields.Boolean(string="Hàng dễ vỡ, vui lòng nhẹ tay")
    note_giao_hang_mot_phan = fields.Boolean(string="Giao hàng một phần, nhận lại sản phẩm từ khách")
    note_khong_giao_duoc_lh = fields.Boolean(string="Không giao được liên hệ SĐT shop, không tự ý hủy đơn")
    note_goi_dien_truoc_khi_giao = fields.Boolean(string="Gọi điện thoại cho khách trước khi giao")
    note_giao_gio_hanh_chinh = fields.Boolean(string="Giao hàng vào giờ hành chính")
    note_khong_cho_xem = fields.Boolean(string="Không cho xem hàng")
    note_khac = fields.Boolean(string="Khác")
    note_khac_input = fields.Char(string="Nội dung khác")

    @api.onchange('note_thu_hang', 'note_xem_hang_khong_thu', 'note_de_vo', 
                 'note_giao_hang_mot_phan', 'note_khong_giao_duoc_lh', 
                 'note_goi_dien_truoc_khi_giao', 'note_giao_gio_hanh_chinh', 
                 'note_khong_cho_xem', 'note_khac', 'note_khac_input')
    def _onchange_note_selections(self):
        notes = []
        if self.note_thu_hang:
            notes.append("Cho khách thử hàng")
        if self.note_xem_hang_khong_thu:
            notes.append("Cho khách xem hàng, không cho thử")
        if self.note_de_vo:
            notes.append("Hàng dễ vỡ, vui lòng nhẹ tay")
        if self.note_giao_hang_mot_phan:
            notes.append("Giao hàng một phần, nhận lại sản phẩm từ khách")
        if self.note_khong_giao_duoc_lh:
            notes.append("Không giao được liên hệ SĐT shop, không tự ý hủy đơn")
        if self.note_goi_dien_truoc_khi_giao:
            notes.append("Gọi điện thoại cho khách trước khi giao")
        if self.note_giao_gio_hanh_chinh:
            notes.append("Giao hàng vào giờ hành chính")
        if self.note_khong_cho_xem:
            notes.append("Không cho xem hàng")
        
        if self.note_khac and self.note_khac_input:
            notes.append(self.note_khac_input)
            
        self.remark = ", ".join(notes)

    # Weight and Dimensions
    weight = fields.Float(string="Trọng lượng (kg)", default=0.1)
    length = fields.Float(string="Dài (cm)", default=10)
    width = fields.Float(string="Rộng (cm)", default=10)
    height = fields.Float(string="Cao (cm)", default=10)

    # Fee Calculation
    estimated_fee = fields.Float(string="Phí vận chuyển dự kiến (VND)", readonly=True)
    estimated_cod_fee = fields.Float(string="Phí COD dự kiến (VND)", readonly=True)
    estimated_insurance_fee = fields.Float(string="Phí bảo hiểm dự kiến (VND)", readonly=True)

    # Sender Info (Editable)
    sender_config_id = fields.Many2one("stock.warehouse", string="Cấu hình gửi/Kho")
    sender_name = fields.Char(string="Tên người gửi", required=True)
    sender_mobile = fields.Char(string="SĐT người gửi", required=True)
    sender_prov_id = fields.Many2one("jnt.province", string="Tỉnh/Thành gửi", ondelete='set null')
    sender_city_id = fields.Many2one("jnt.district", string="Quận/Huyện gửi", ondelete='set null',
                                    domain="[('province_id', '=', sender_prov_id)]")
    sender_area_id = fields.Many2one("jnt.ward", string="Phường/Xã gửi", ondelete='set null',
                                    domain="[('district_id', '=', sender_city_id)]")
    sender_address = fields.Char(string="Địa chỉ gửi", required=True)

    @api.onchange('sender_config_id')
    def _onchange_sender_config_id(self):
        if self.sender_config_id:
            warehouse = self.sender_config_id
            sender_partner = warehouse.partner_id or self.picking_id.company_id.partner_id
            
            self.sender_name = warehouse.jnt_sender_name or sender_partner.name
            self.sender_mobile = warehouse.jnt_sender_mobile or (sender_partner.mobile or sender_partner.phone or '').replace(' ', '').replace('+84', '0')
            self.sender_address = warehouse.jnt_sender_address or sender_partner.street
            
            if warehouse.jnt_prov_id:
                self.sender_prov_id = warehouse.jnt_prov_id
            if warehouse.jnt_city_id:
                self.sender_city_id = warehouse.jnt_city_id
            if warehouse.jnt_area_id:
                self.sender_area_id = warehouse.jnt_area_id
        else:
            # Revert to warehouse defaults if config is cleared
            warehouse = self.warehouse_id
            if warehouse:
                sender_partner = warehouse.partner_id or self.picking_id.company_id.partner_id
                self.sender_name = warehouse.jnt_sender_name or sender_partner.name
                self.sender_mobile = warehouse.jnt_sender_mobile or (sender_partner.mobile or sender_partner.phone or '').replace(' ', '').replace('+84', '0')
                self.sender_address = warehouse.jnt_sender_address or sender_partner.street
                self.sender_prov_id = warehouse.jnt_prov_id
                self.sender_city_id = warehouse.jnt_city_id
                self.sender_area_id = warehouse.jnt_area_id

    @api.onchange('sender_prov_id')
    def _onchange_sender_prov_id(self):
        if self.sender_prov_id:
            return {'domain': {'sender_city_id': [('province_id', '=', self.sender_prov_id.id)]}}
        else:
            return {'domain': {'sender_city_id': []}}

    @api.onchange('sender_city_id')
    def _onchange_sender_city_id(self):
        if self.sender_city_id:
            return {'domain': {'sender_area_id': [('district_id', '=', self.sender_city_id.id)]}}
        else:
            return {'domain': {'sender_area_id': []}}

    # Receiver Info (Editable)
    receiver_name = fields.Char(string="Tên người nhận", required=True)
    receiver_mobile = fields.Char(string="SĐT người nhận", required=True)
    receiver_prov_id = fields.Many2one("jnt.province", string="Tỉnh/Thành nhận", ondelete='set null')
    receiver_city_id = fields.Many2one("jnt.district", string="Quận/Huyện nhận", ondelete='set null', 
                                      domain="[('province_id', '=', receiver_prov_id)]")
    receiver_area_id = fields.Many2one("jnt.ward", string="Phường/Xã nhận", ondelete='set null',
                                      domain="[('district_id', '=', receiver_city_id)]")
    receiver_address = fields.Char(string="Địa chỉ nhận", required=True)

    @api.onchange('sender_area_id')
    def _onchange_sender_area_id(self):
        pass

    @api.onchange('receiver_area_id')
    def _onchange_receiver_area_id(self):
        # Auto-calculate fee when location changes
        self._auto_calculate_fee()

    @api.onchange('weight', 'goods_value', 'cod_money', 'is_insured')
    def _onchange_fee_params(self):
        # Auto-calculate fee when weight or values change
        self._auto_calculate_fee()

    def _auto_calculate_fee(self):
        """Auto-calculate shipping fee when all required fields are filled"""
        if not (self.weight and self.sender_area_id and self.receiver_area_id):
            return

        try:
            get_param = self.env['ir.config_parameter'].sudo().get_param
            api_account = get_param('jnt_apiAccount')
            private_key = get_param('jnt_privateKey')
            jnt_customer_code = get_param('jnt_customerCode')
            jnt_password = get_param('jnt_password')
            company = self.picking_id.company_id if self.picking_id else self.env.company

            if not all([api_account, private_key, jnt_customer_code, jnt_password]):
                return

            client = JTApiUtils(
                api_account=api_account,
                private_key=private_key,
                environment=company.jt_environment
            )

            biz_params = {
                "customerCode": jnt_customer_code,
                "password": jnt_password.upper(),
                "weight": self.weight,
                "productType": self.product_type or 'EXPRESS',
                "goodsType": self.goods_type or 'bm000010',
                "goodsValue": max(self.goods_value, 1.0),
                "codMoney": str(int(self.cod_money)) if self.cod_money else "0",
                "isInsured": 1 if self.is_insured else 0,
                "sender": {
                    "prov": (self.sender_prov_id.name or "").strip(),
                    "city": (self.sender_city_id.name or "").strip(),
                    "area": self.sender_area_id.name if self.sender_area_id else ""
                },
                "receiver": {
                    "prov": (self.receiver_prov_id.name or "").strip(),
                    "city": (self.receiver_city_id.name or "").strip(),
                    "area": self.receiver_area_id.name if self.receiver_area_id else ""
                }
            }

            result = client.calculate_fee(biz_params)
            if result.get('code') == '1' and result.get('data'):
                data = result['data']
                self.estimated_fee = float(data.get('price', 0))
                self.estimated_cod_fee = float(data.get('codfee', 0) or data.get('codFee', 0))
                self.estimated_insurance_fee = float(data.get('insurancefee', 0) or data.get('insuranceFee', 0))
                _logger.info("J&T Fee calculated: %s VND (COD: %s, Insurance: %s)", 
                            self.estimated_fee, self.estimated_cod_fee, self.estimated_insurance_fee)
            else:
                _logger.warning("J&T Fee calculation failed: %s", result.get('msg'))
        except Exception as e:
            _logger.error("Error calculating J&T fee: %s", e)

    @api.onchange('receiver_prov_id')
    def _onchange_receiver_prov_id(self):
        if self.receiver_prov_id:
            return {'domain': {'receiver_city_id': [('province_id', '=', self.receiver_prov_id.id)]}}
        else:
            return {'domain': {'receiver_city_id': []}}

    @api.onchange('receiver_city_id')
    def _onchange_receiver_city_id(self):
        if self.receiver_city_id:
            return {'domain': {'receiver_area_id': [('district_id', '=', self.receiver_city_id.id)]}}
        else:
            return {'domain': {'receiver_area_id': []}}

    def _normalize_name(self, name):
        if not name: return ""
        name = str(name).lower().strip()
        prefixes = [
            'tỉnh ', 'thành phố ', 'quận ', 'huyện ', 'thị xã ', 
            'phường ', 'xã ', 'thị trấn ', 'tp. ', 'tp ', 'q. ', 'h. ', 'p. ', 'x. '
        ]
        for p in prefixes:
            if name.startswith(p):
                name = name[len(p):]
        return name.strip()

    @api.model
    def action_sync_jnt_codes(self):
        """Sync J&T dedicated locations from the local JSON data file."""
        import json
        import os
        import logging
        from odoo import _
        from odoo.exceptions import UserError
        from odoo.modules.module import get_module_resource

        _logger = logging.getLogger(__name__)

        json_path = get_module_resource('hlv_delivery_jt', 'data', 'jnt_mapping.json')
        if not json_path or not os.path.exists(json_path):
            raise UserError(_("Không tìm thấy file dữ liệu mapping J&T!"))

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
        except Exception as e:
            raise UserError(_("Lỗi đọc file mapping: %s") % e)

        # Cleanup old wizards to avoid foreign key constraints blocking sync
        self.env['jt.create.order.wizard'].sudo().search([]).unlink()

        created_p = 0
        created_d = 0
        created_w = 0

        for item in mapping_data:
            # item format from our converter: {'p': 'norm_p', 'd': 'norm_d', 'w': 'full_ward_name', 'c': 'code'}
            # Wait, the converter used normalize for prov and dist too. 
            # I should probably use the raw names for the records.
            pass

        # RE-IMPLEMENTING SYNC TO USE NEW MODELS PROPERLY
        # I'll need to re-read the Excel or update the JSON converter to include raw names.
        # Actually, let's just use the normalized for now or better, re-read JSON if I update it.
        # Let's update the JSON converter first to be more robust.
        return self._sync_from_mapping_data(mapping_data)

    def _sync_from_mapping_data(self, mapping_data):
        Province = self.env['jnt.province']
        District = self.env['jnt.district']
        Ward = self.env['jnt.ward']

        prov_map = {p.name: p.id for p in Province.search([])}
        dist_map = {} # (prov_id, name): id
        for d in District.search([]):
            dist_map[(d.province_id.id, d.name)] = d.id
        
        ward_map = {} # (dist_id, name): id
        for w in Ward.search([]):
            ward_map[(w.district_id.id, w.name)] = w.id

        updated = 0
        for item in mapping_data:
            p_name = item.get('pn', item['p']) # Use 'pn' for raw name if I update converter
            d_name = item.get('dn', item['d'])
            w_name = item['w'] # This is "Phường...-code"
            code = item['c']

            p_id = prov_map.get(p_name)
            if not p_id:
                p_id = Province.create({'name': p_name}).id
                prov_map[p_name] = p_id
            
            d_id = dist_map.get((p_id, d_name))
            if not d_id:
                d_id = District.create({'name': d_name, 'province_id': p_id}).id
                dist_map[(p_id, d_name)] = d_id
            
            w_id = ward_map.get((d_id, w_name))
            if not w_id:
                Ward.create({'name': w_name, 'jnt_code': code, 'district_id': d_id})
                updated += 1
                ward_map[(d_id, w_name)] = True # Just mark as exists

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã đồng bộ {updated} Phường/Xã vào danh mục J&T.',
                'type': 'success',
                'sticky': True,
            }
        }

    @api.model
    def default_get(self, fields_list):
        res = super(JTCreateOrderWizard, self).default_get(fields_list)
        if self._context.get('active_id'):
            picking = self.env['stock.picking'].browse(self._context.get('active_id'))
            company = picking.company_id
            warehouse = picking.picking_type_id.warehouse_id
            
            sender_partner = warehouse.partner_id or company.partner_id
            receiver_partner = picking.partner_id

            # Cache Jnt records for faster mapping
            JntProvince = self.env['jnt.province']
            JntDistrict = self.env['jnt.district']
            JntWard = self.env['jnt.ward']

            def get_jnt_ids(prov_name, dist_name, ward_name):
                p = JntProvince.search([('name', 'ilike', self._normalize_name(prov_name))], limit=1)
                if not p:
                    p = JntProvince.search([('name', 'ilike', prov_name.strip())], limit=1)
                
                d = JntDistrict.browse()
                if p:
                    d = JntDistrict.search([('province_id', '=', p.id), ('name', 'ilike', self._normalize_name(dist_name))], limit=1)
                    if not d:
                        d = JntDistrict.search([('province_id', '=', p.id), ('name', 'ilike', dist_name.strip())], limit=1)
                
                w = JntWard.browse()
                if d:
                    w = JntWard.search([('district_id', '=', d.id), ('name', 'ilike', ward_name.strip())], limit=1)
                
                return p.id, d.id, w.id

            # Receiver Address from Picking/Partner - REMOVED GHN MAPPING
            r_prov_name = receiver_partner.state_id.name or ''
            r_dist_name = receiver_partner.city or ''
            r_ward_name = receiver_partner.street2 or ''
            
            r_p, r_d, r_w = get_jnt_ids(r_prov_name, r_dist_name, r_ward_name)

            # Sender Address from Company/Warehouse
            s_name = sender_partner.name or ''
            s_mobile = (sender_partner.mobile or sender_partner.phone or '').replace(' ', '').replace('+84', '0')
            s_address = sender_partner.street or ''
            
            s_prov_name = sender_partner.state_id.name or ''
            s_dist_name = sender_partner.city or ''
            s_ward_name = sender_partner.street2 or ''
            
            s_p, s_d, s_w = get_jnt_ids(s_prov_name, s_dist_name, s_ward_name)

            # Override with Warehouse J&T specific fields if set
            if warehouse:
                if warehouse.jnt_sender_name: s_name = warehouse.jnt_sender_name
                if warehouse.jnt_sender_mobile: s_mobile = warehouse.jnt_sender_mobile
                if warehouse.jnt_sender_address: s_address = warehouse.jnt_sender_address
                
                if warehouse.jnt_prov_id: s_p = warehouse.jnt_prov_id.id
                if warehouse.jnt_city_id: s_d = warehouse.jnt_city_id.id
                if warehouse.jnt_area_id: s_w = warehouse.jnt_area_id.id

            res.update({
                'picking_id': picking.id,
                'sender_config_id': warehouse.id if warehouse else False,
                'cod_money': picking.sale_id.amount_total if (picking.sale_id and picking.sale_id.amount_total > 0) else 0.0,
                'goods_value': picking.sale_id.amount_total if (picking.sale_id and picking.sale_id.amount_total > 0) else 0.0,
                
                'sender_name': s_name,
                'sender_mobile': s_mobile,
                'sender_prov_id': s_p,
                'sender_city_id': s_d,
                'sender_area_id': s_w,
                'sender_address': s_address,

                'receiver_name': receiver_partner.name or '',
                'receiver_mobile': (receiver_partner.mobile or receiver_partner.phone or '').replace(' ', '').replace('+84', '0'),
                'receiver_prov_id': r_p,
                'receiver_city_id': r_d,
                'receiver_area_id': r_w,
                'receiver_address': receiver_partner.street or '',
            })
            # Try to get weight from picking/move lines if possible
            total_weight = sum(move.product_id.weight * move.product_uom_qty for move in picking.move_ids)
            if total_weight > 0:
                res['weight'] = total_weight
        return res

    def action_create_jt_order(self):
        self.ensure_one()
        # Locations are now dedicated records, no need to save codes back to GHN/Partner

        company = self.picking_id.company_id
        get_param = self.env['ir.config_parameter'].sudo().get_param
        api_account = get_param('jnt_apiAccount')
        private_key = get_param('jnt_privateKey')
        jnt_customer_code = get_param('jnt_customerCode')
        # jnt_password is the 32-char MD5 password string provided by J&T
        jnt_password = get_param('jnt_password')

        if api_account:
            api_account = api_account.strip()
        if private_key:
            private_key = private_key.strip()
        if jnt_customer_code:
            jnt_customer_code = jnt_customer_code.strip()
        if jnt_password:
            jnt_password = jnt_password.strip()

        if not api_account or not private_key or not jnt_customer_code or not jnt_password:
            raise UserError(_("Thiếu thông tin cấu hình J&T (apiAccount, privateKey, customerCode, password) trong System Parameters!"))

        _logger.info("J&T Auth Check | Account: %s | Customer: %s | Env: %s", 
                     api_account, jnt_customer_code, company.jt_environment)

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

        if not self.sender_area_id or not self.receiver_area_id:
            raise UserError(_("Vui lòng chọn đầy đủ Tỉnh/Thành, Quận/Huyện, Phường/Xã cho cả người gửi và người nhận."))

        # J&T requires prov, city, area. Odoo has state_id, city, and maybe street2 as area.
        # This will need mapping if the address structure is different.
        
        # Use the 32-char MD5 password string provided by J&T
        # Must be UPPERCASE as shown in J&T API documentation example
        password_to_send = jnt_password.upper()
        
        _logger.info("J&T Password | customerCode: %s | password: %s", jnt_customer_code, password_to_send)

        _logger.info("J&T Create Order | Account: %s | Customer: %s | Env: %s", 
                     api_account, jnt_customer_code, company.jt_environment)

        def sanitize_name(name, length=40):
            return (name or "")[:length]

        def sanitize_address(addr, length=250):
            return (addr or "")[:length]

        # J&T Vietnam uses specific string formats for many fields
        # Ensure goodsValue is at least 1 as J&T rejects 0
        goods_val = max(self.goods_value, 1.0)
        goods_val_str = str(int(goods_val))
        cod_money_str = str(int(self.cod_money))
        # Ensure weight is at least 0.01 to satisfy J&T requirements
        weight_val = max(self.weight, 0.01)
        weight_str = "{:.2f}".format(weight_val)

        # Payload
        picking = self.picking_id
        customer_code = jnt_customer_code # Use the already defined jnt_customer_code
        biz_params = {
            "customerCode": customer_code,
            "password": password_to_send,
            "txlogisticId": picking.name.replace("/", "-"),
            "orderType": self.order_type,
            "serviceType": self.service_type,
            "deliveryType": self.delivery_type,
            "selfAddress": 0,
            "productType": self.product_type,
            "goodsType": self.goods_type,
            "sender": {
                "name": sanitize_name(self.sender_name),
                "mobile": self.sender_mobile or "",
                "prov": (self.sender_prov_id.name or "").strip(),
                "city": (self.sender_city_id.name or "").strip(),
                "area": (self.sender_area_id.name or "").strip(),
                "address": sanitize_address(self.sender_address)
            },
            "receiver": {
                "name": sanitize_name(self.receiver_name),
                "mobile": self.receiver_mobile or "",
                "prov": (self.receiver_prov_id.name or "").strip(),
                "city": (self.receiver_city_id.name or "").strip(),
                "area": (self.receiver_area_id.name or "").strip(),
                "address": sanitize_address(self.receiver_address)
            },
            "payType": self.pay_type,
            "partSign": "1" if self.part_sign else "0",
            "goodsValue": goods_val_str,
            "codMoney": cod_money_str,
            "remark": self.remark or "",
            "packageInfo": {
                "weight": weight_str,
                "length": int(self.length),
                "width": int(self.width),
                "height": int(self.height),
                "volume": str(int(max(self.length * self.width * self.height / 6000.0, 1.0)))
            },
            "itemsValue": goods_val_str,
            "totalQuantity": len(picking.move_ids_without_package),
            "items": [{
                "itemName": line.product_id.name[:100],
                "englishName": line.product_id.name[:100],
                "number": str(int(line.product_uom_qty)),
                "itemValue": int(line.product_id.list_price or 1) # Ensure item value is at least 1 and is a number
            } for line in picking.move_ids_without_package]
        }

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
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        else:
            raise UserError(_("Lỗi từ J&T: %s") % result.get('msg', 'Unknown Error'))
