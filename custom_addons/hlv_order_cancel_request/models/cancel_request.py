from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SaleOrderCancelRequest(models.Model):
    _name = 'sale.order.cancel.request'
    _description = 'Yêu cầu Hủy Đơn Hàng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Mã Yêu Cầu', required=True, copy=False, readonly=True, index=True, default=lambda self: _('Mới'))
    salesperson_name = fields.Char(string='Mã Sale', required=True, tracking=True)
    order_reference = fields.Char(string='Mã Đơn Hàng', required=True, tracking=True, help="Mã đơn hàng được nhập bởi Sale, ví dụ: SO12345")
    
    order_id = fields.Many2one('sale.order', string='Đơn Bán Hàng', compute='_compute_order_id', store=True, readonly=False)
    warehouse_id = fields.Many2one('stock.warehouse', string='Kho', compute='_compute_warehouse_id', store=True)
    
    type = fields.Selection([
        ('cancel', 'Hủy Đơn'),
        ('modify', 'Chỉnh Sửa')
    ], string='Loại Yêu Cầu', default='cancel', required=True, tracking=True)
    
    reason = fields.Text(string='Lý do', required=True, tracking=True)
    
    # Flow: YCHD → Kho XN → Kế toán XN → Hoàn Thành
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('submitted', 'YCHD'),
        ('warehouse_confirmed', 'Kho XN'),
        ('accountant_confirmed', 'Kế toán XN'),
        ('done', 'Hoàn Thành'),
        ('rejected', 'Đã Từ Chối')
    ], string='Trạng Thái', default='draft', tracking=True, group_expand='_expand_states')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Mới')) == _('Mới'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.order.cancel.request') or _('Mới')
        return super(SaleOrderCancelRequest, self).create(vals_list)

    @api.depends('order_reference')
    def _compute_order_id(self):
        for rec in self:
            if rec.order_reference:
                order = self.env['sale.order'].search([('name', '=', rec.order_reference)], limit=1)
                rec.order_id = order.id if order else False
            else:
                rec.order_id = False

    @api.depends('order_id')
    def _compute_warehouse_id(self):
        """Get warehouse from the first outgoing picking of the sale order."""
        StockPicking = self.env['stock.picking'].sudo()
        for rec in self:
            if rec.order_id:
                # Search for pickings related to this sale order
                pickings = StockPicking.search([
                    ('origin', '=', rec.order_id.name),
                    ('picking_type_code', '=', 'outgoing')
                ], limit=1)
                if pickings:
                    rec.warehouse_id = pickings.picking_type_id.warehouse_id
                else:
                    # Fallback: try to get warehouse from sale order directly
                    rec.warehouse_id = rec.order_id.warehouse_id if hasattr(rec.order_id, 'warehouse_id') else False
            else:
                rec.warehouse_id = False

    # ============ Actions ============

    def action_submit(self):
        """Sale submits the request."""
        self.ensure_one()
        self.state = 'submitted'
        self._send_zalo_notification_on_submit()

    def action_warehouse_confirm(self):
        """Warehouse confirms they have handled the goods (stopped packing or updated)."""
        self.ensure_one()
        # Check permission
        if not self.env.user.has_group('hlv_order_cancel_request.group_cancel_request_warehouse'):
            raise UserError(_("Bạn không có quyền xác nhận bước Kho. Chỉ Thủ Kho mới có thể thực hiện."))
        self.state = 'warehouse_confirmed'
        self._send_zalo_notification_on_warehouse_confirm()

    def action_accountant_confirm(self):
        """Accountant confirms they have processed the request in external system."""
        self.ensure_one()
        # Check permission
        if not self.env.user.has_group('hlv_order_cancel_request.group_cancel_request_accountant'):
            raise UserError(_("Bạn không có quyền xác nhận bước Kế Toán. Chỉ Kế Toán mới có thể thực hiện."))
        self.state = 'accountant_confirmed'
        self._send_zalo_notification_on_accountant_confirm()

    def action_done(self):
        """Mark request as completed."""
        self.ensure_one()
        self.state = 'done'

    def action_reject(self):
        self.state = 'rejected'
        
    def action_draft(self):
        self.state = 'draft'

    def _expand_states(self, states, domain, order):
        return [key for key, val in type(self).state.selection]

    # ============ Zalo Notification Helpers ============

    def _parse_warehouse_mapping(self):
        """
        Parse warehouse mapping from config.
        Format: KHO1:UID1,UID2|KHO2:UID3|KHO3:UID4
        Returns: dict { 'TSN': ['123456', '789012'], 'KBC': ['999888'] }
        """
        Config = self.env['ir.config_parameter'].sudo()
        mapping_text = Config.get_param('hlv_order_cancel_request.warehouse_zalo_mapping', '')
        
        mapping = {}
        if not mapping_text:
            return mapping
        
        # Split by | (pipe) for multiple warehouses
        for entry in mapping_text.split('|'):
            entry = entry.strip()
            if not entry or ':' not in entry:
                continue
            parts = entry.split(':', 1)
            code = parts[0].strip().upper()
            uid_text = parts[1].strip()
            if code and uid_text:
                # Support multiple UIDs separated by comma
                uids = [u.strip() for u in uid_text.split(',') if u.strip()]
                if uids:
                    mapping[code] = uids
        return mapping

    def _get_warehouse_recipients(self):
        """
        Get Warehouse Zalo UIDs based on the order's warehouse.
        Looks up from warehouse mapping in config. Supports multiple UIDs per warehouse.
        """
        if not self.warehouse_id:
            return []
        
        mapping = self._parse_warehouse_mapping()
        warehouse_code = self.warehouse_id.code or ''
        
        uids = mapping.get(warehouse_code.upper(), [])
        return uids

    def _parse_accountant_mapping(self):
        """
        Parse accountant mapping from config.
        Format: KHO1:UID1,UID2|KHO2:UID3|KHO3:UID4
        Returns: dict { 'TSN': ['123456', '789012'], 'KBC': ['999888'] }
        """
        Config = self.env['ir.config_parameter'].sudo()
        mapping_text = Config.get_param('hlv_order_cancel_request.accountant_zalo_mapping', '')
        
        mapping = {}
        if not mapping_text:
            return mapping
        
        # Split by | (pipe) for multiple warehouses
        for entry in mapping_text.split('|'):
            entry = entry.strip()
            if not entry or ':' not in entry:
                continue
            parts = entry.split(':', 1)
            code = parts[0].strip().upper()
            uid_text = parts[1].strip()
            if code and uid_text:
                # Support multiple UIDs separated by comma
                uids = [u.strip() for u in uid_text.split(',') if u.strip()]
                if uids:
                    mapping[code] = uids
        return mapping

    def _get_accountant_recipients(self):
        """
        Get Accountant Zalo UIDs based on the order's warehouse.
        Looks up from accountant mapping in config. Supports multiple UIDs per warehouse.
        """
        if not self.warehouse_id:
            return []
        
        mapping = self._parse_accountant_mapping()
        warehouse_code = self.warehouse_id.code or ''
        
        uids = mapping.get(warehouse_code.upper(), [])
        return uids

    def _get_sale_recipients(self):
        """
        Get Sale's Zalo UID from saler_mapping_text in ZNS config.
        Uses salesperson_name (mã sale) to lookup the Zalo UID.
        """
        if not self.salesperson_name:
            return []
        
        zalo_config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
        if not zalo_config:
            return []
        
        user_ids = zalo_config.get_saler_user_ids_from_mapping(self.salesperson_name)
        return user_ids

    def _get_backend_url(self):
        """Get backend URL for this request."""
        action_id = self.env.ref('hlv_order_cancel_request.action_sale_order_cancel_request').id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/odoo/action-{action_id}/{self.id}"

    def _get_type_label(self):
        """Get human-readable type label (Hủy Đơn / Chỉnh Sửa)."""
        return dict(self._fields['type'].selection).get(self.type, self.type)

    def _send_zalo_to_recipients(self, recipients, message):
        """Send Zalo notification to specific recipients."""
        if not recipients:
            return

        zalo_config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
        if not zalo_config:
            return

        for uid in recipients:
            try:
                zalo_config.send_notification_message(uid, message)
            except Exception:
                pass

    # ============ Notification Methods ============

    def _send_zalo_notification_on_submit(self):
        """
        Step 1: Sale submits request.
        Recipients: Warehouse (specific to order's warehouse) + Accountant
        """
        self.ensure_one()
        type_label = self._get_type_label().upper()
        warehouse_name = self.warehouse_id.name if self.warehouse_id else 'N/A'
        
        # Message for Warehouse - to pause packing
        msg_warehouse = f"⏸️ TẠM DỪNG ĐÓNG GÓI - YÊU CẦU {type_label}\n"
        msg_warehouse += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
            msg_warehouse += f"• Đơn Odoo: {self.order_id.name}\n"
        msg_warehouse += f"• Kho: {warehouse_name}\n"
        msg_warehouse += f"• Lý do: {self.reason}\n"
        msg_warehouse += f"• Mã YC: {self.name}\n"
        msg_warehouse += f"👉 {self._get_backend_url()}"
        
        # Message for Accountant - notification only (they confirm later)
        msg_accountant = f"🔔 YÊU CẦU {type_label} MỚI\n"
        msg_accountant += f"• Sale: {self.salesperson_name}\n"
        msg_accountant += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
            msg_accountant += f"• Đơn Odoo: {self.order_id.name}\n"
        msg_accountant += f"• Kho: {warehouse_name}\n"
        msg_accountant += f"• Lý do: {self.reason}\n"
        msg_accountant += f"Chờ Kho xác nhận trước."
        
        self._send_zalo_to_recipients(self._get_warehouse_recipients(), msg_warehouse)
        self._send_zalo_to_recipients(self._get_accountant_recipients(), msg_accountant)

    def _send_zalo_notification_on_warehouse_confirm(self):
        """
        Step 2: Warehouse confirms they handled the goods.
        Recipients: Accountant (to process in external system and confirm)
        """
        self.ensure_one()
        type_label = self._get_type_label().upper()
        
        if self.type == 'cancel':
            msg = f"📋 KHO ĐÃ XÁC NHẬN DỪNG ĐÓNG GÓI\n"
            msg += f"Vui lòng hủy đơn trên hệ thống kế toán và xác nhận.\n"
        else:
            msg = f"📋 KHO ĐÃ XÁC NHẬN KIỂM TRA XONG\n"
            msg += f"Vui lòng chỉnh sửa trên hệ thống kế toán và xác nhận.\n"
        
        msg += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
            msg += f"• Đơn Odoo: {self.order_id.name}\n"
        msg += f"• Mã YC: {self.name}\n"
        msg += f"👉 {self._get_backend_url()}"
        
        self._send_zalo_to_recipients(self._get_accountant_recipients(), msg)

    def _send_zalo_notification_on_accountant_confirm(self):
        """
        Step 3: Accountant confirms they processed in external system.
        Recipients: Sale who created the request
        """
        self.ensure_one()
        
        if self.type == 'cancel':
            msg = f"✅ YÊU CẦU HỦY ĐƠN ĐÃ HOÀN TẤT\n"
        else:
            msg = f"✅ YÊU CẦU CHỈNH SỬA ĐÃ HOÀN TẤT\n"
        
        msg += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
            msg += f"• Đơn Odoo: {self.order_id.name}\n"
        msg += f"• Mã YC: {self.name}\n"
        msg += "Kho và Kế toán đã xử lý xong. Có thể tiến hành xóa/sửa đơn hàng."
        
        self._send_zalo_to_recipients(self._get_sale_recipients(), msg)
