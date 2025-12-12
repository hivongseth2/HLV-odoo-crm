from odoo import models, fields, api, _

class SaleOrderCancelRequest(models.Model):
    _name = 'sale.order.cancel.request'
    _description = 'Yêu cầu Hủy Đơn Hàng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Mã Yêu Cầu', required=True, copy=False, readonly=True, index=True, default=lambda self: _('Mới'))
    salesperson_name = fields.Char(string='Tên Sale / Mã Sale', required=True, tracking=True)
    order_reference = fields.Char(string='Mã Đơn Hàng', required=True, tracking=True, help="Mã đơn hàng được nhập bởi Sale, ví dụ: SO12345")
    
    order_id = fields.Many2one('sale.order', string='Đơn Bán Hàng', compute='_compute_order_id', store=True, readonly=False)
    
    type = fields.Selection([
        ('cancel', 'Hủy Đơn'),
        ('modify', 'Chỉnh Sửa')
    ], string='Loại Yêu Cầu', default='cancel', required=True, tracking=True)
    
    reason = fields.Text(string='Lý do', required=True, tracking=True)
    
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('submitted', 'Đã Gửi'),
        ('done', 'Hoàn Thành'),
        ('rejected', 'Đã Từ Chối')
    ], string='Trạng Thái', default='draft', tracking=True, group_expand='_expand_states')

    @api.model
    def create(self, vals):
        if vals.get('name', _('Mới')) == _('Mới'):
            vals['name'] = self.env['ir.sequence'].next_by_code('sale.order.cancel.request') or _('Mới')
        return super(SaleOrderCancelRequest, self).create(vals)

    @api.depends('order_reference')
    def _compute_order_id(self):
        for rec in self:
            if rec.order_reference:
                # Try to find exact match
                order = self.env['sale.order'].search([('name', '=', rec.order_reference)], limit=1)
                rec.order_id = order.id if order else False
            else:
                rec.order_id = False

    def action_submit(self):
        self.ensure_one()
        self.state = 'submitted'
        self._send_zalo_notification_on_submit()

    def action_done(self):
        self.state = 'done'
        self._send_zalo_notification_on_done()

    def action_reject(self):
        self.state = 'rejected'
        
    def action_draft(self):
        self.state = 'draft'

    def _expand_states(self, states, domain, order):
        return [key for key, val in type(self).state.selection]

    def _send_zalo_notification_on_submit(self):
        """
        Send Zalo notification to Accountant and Warehouse when a request is submitted.
        """
        # Get recipients from config
        Config = self.env['ir.config_parameter'].sudo()
        accountant_uid = Config.get_param('hlv_order_cancel_request.accountant_zalo_uid')
        warehouse_uid = Config.get_param('hlv_order_cancel_request.warehouse_zalo_uid')
        
        recipients = []
        if accountant_uid: recipients.append(accountant_uid)
        if warehouse_uid: recipients.append(warehouse_uid)
        
        if not recipients:
            return

        action_id = self.env.ref('hlv_order_cancel_request.action_sale_order_cancel_request').id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        backend_url = f"{base_url}/odoo/action-{action_id}/{self.id}"

        type_label = dict(self._fields['type'].selection).get(self.type, self.type).upper()

        # Build message
        msg = f"🔔 XÁC NHẬN YÊU CẦU {type_label} ĐƠN HÀNG\n"
        msg += f"• Sale: {self.salesperson_name}\n"
        msg += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
             msg += f"• Đơn Odoo: {self.order_id.name}\n"
        msg += f"• Lý do: {self.reason}\n"
        msg += f"• ID Yêu cầu: {self.name}\n"
        msg += f"👉 Xem chi tiết: {backend_url}"

        # Send via hlv_zalo_zns config
        # We need an active Zalo config to send messages
        zalo_config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
        if not zalo_config:
            # Fallback or log warning if no zalo config found
            return

        for uid in recipients:
             # Clean up UID if comma separated
             uids = [u.strip() for u in uid.split(',') if u.strip()]
             for u in uids:
                 try:
                     zalo_config.send_notification_message(u, msg)
                 except Exception as e:
                     # Log error but don't stop flow
                     pass

    def _send_zalo_notification_on_done(self):
        """
        Send Zalo notification to Accountant and Warehouse when a request is done/processed.
        """
        # Get recipients from config
        Config = self.env['ir.config_parameter'].sudo()
        accountant_uid = Config.get_param('hlv_order_cancel_request.accountant_zalo_uid')
        warehouse_uid = Config.get_param('hlv_order_cancel_request.warehouse_zalo_uid')
        
        recipients = []
        if accountant_uid: recipients.append(accountant_uid)
        if warehouse_uid: recipients.append(warehouse_uid)
        
        if not recipients:
            return

        # Build message
        action_id = self.env.ref('hlv_order_cancel_request.action_sale_order_cancel_request').id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        backend_url = f"{base_url}/odoo/action-{action_id}/{self.id}"

        type_label = dict(self._fields['type'].selection).get(self.type, self.type).upper()

        # Build message
        msg = f"✅ ĐƠN HÀNG ĐÃ HỦY TRÊN MISA\n"
        msg += f"• Sale: {self.salesperson_name}\n"
        msg += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
             msg += f"• Đơn Odoo: {self.order_id.name}\n"
        msg += f"• Lý do: {self.reason}\n"
        msg += f"• ID Yêu cầu: {self.name}\n"
        msg += f"👉 Xem chi tiết: {backend_url}"

        # Send via hlv_zalo_zns config
        # We need an active Zalo config to send messages
        zalo_config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
        if not zalo_config:
            # Fallback or log warning if no zalo config found
            return

        for uid in recipients:
             # Clean up UID if comma separated
             uids = [u.strip() for u in uid.split(',') if u.strip()]
             for u in uids:
                 try:
                     zalo_config.send_notification_message(u, msg)
                 except Exception as e:
                     # Log error but don't stop flow
                     pass
