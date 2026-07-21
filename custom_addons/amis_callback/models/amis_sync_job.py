# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MAX_RETRY = 5


class AmisSyncJob(models.Model):
    _name = 'amis.sync.job'
    _description = 'Hàng đợi đồng bộ MISA'
    _order = 'create_date asc'
    _rec_name = 'create_date'

    picking_id = fields.Many2one(
        'stock.picking', string='Phiếu kho', required=False, ondelete='cascade', index=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Đơn bán hàng', required=False, ondelete='cascade', index=True,
    )
    purchase_order_id = fields.Many2one(
        'purchase.order', string='Đơn mua hàng', required=False, ondelete='cascade', index=True,
    )
    payment_request_id = fields.Many2one(
        'amis.payment.request', string='Đề nghị chi MISA', required=False, ondelete='cascade', index=True,
    )
    direction = fields.Selection([
        ('purchase_order', 'Đơn mua hàng (pu_order)'),
        ('purchase_order_revoke', 'Thu hồi Đơn mua hàng MISA'),
        ('payment_request', 'Đề nghị chi tiền (ba_withdraw)'),
        ('payment_request_revoke', 'Thu hồi đề nghị chi tiền'),
        ('incoming', 'Nhập kho (InwardVoucher)'),
        ('outgoing', 'Xuất kho / Bán hàng (SAVoucher)'),
        ('sa_invoice', 'Hóa đơn bán hàng (SAInvoice)'),
    ], string='Loại đồng bộ', required=True)
    status = fields.Selection([
        ('pending', 'Chờ xử lý'),
        ('done', 'Thành công'),
        ('error', 'Lỗi'),
        ('skipped', 'Bỏ qua'),
    ], string='Trạng thái', default='pending', index=True)
    retry_count = fields.Integer(string='Số lần thử', default=0)
    error_msg = fields.Text(string='Lỗi cuối')
    processed_at = fields.Datetime(string='Xử lý lúc')

    @api.model_create_multi
    def create(self, vals_list):
        jobs = super().create(vals_list)
        if any(job.status == 'pending' for job in jobs):
            cron = self.env.ref(
                'amis_callback.ir_cron_amis_sync_queue',
                raise_if_not_found=False,
            )
            if cron:
                cron.sudo()._trigger()
        return jobs

    @api.model
    def _process_pending(self):
        """Được gọi bởi ir.cron. Xử lý tất cả job pending theo thứ tự."""
        # Chỉ lấy IDs trước, không giữ recordset trong suốt vòng lặp
        job_ids = self.search([
            ('status', '=', 'pending'),
            ('retry_count', '<', MAX_RETRY),
        ]).ids
        _logger.info('AMIS sync queue: xử lý %d jobs', len(job_ids))
        for job_id in job_ids:
            # Mỗi job dùng cursor riêng để tránh 1 HTTP timeout làm block cả batch OK 1
            try:
                import odoo
                with odoo.registry(self.env.cr.dbname).cursor() as cr:
                    env = odoo.api.Environment(cr, self.env.uid, {})
                    job = env['amis.sync.job'].browse(job_id)
                    if job.status != 'pending':
                        continue
                    job._execute()
                    cr.commit()
            except Exception:
                _logger.exception('AMIS sync job %d: unhandled error in cursor', job_id)

    def _execute(self):
        self.ensure_one()
        pick = self.picking_id
        so = self.sale_order_id
        po = self.purchase_order_id
        payment_request = self.payment_request_id
        try:
            if self.direction == 'purchase_order':
                if po:
                    po._sync_purchase_order_to_misa()
                else:
                    raise ValueError('purchase_order job thieu purchase_order_id')
            elif self.direction == 'purchase_order_revoke':
                if po:
                    po._revoke_misa_purchase_order_for_replacement()
                else:
                    raise ValueError('purchase_order_revoke job thiếu purchase_order_id')
            elif self.direction == 'payment_request':
                if payment_request:
                    payment_request._sync_payment_request_to_misa()
                else:
                    raise ValueError('payment_request job thiếu payment_request_id')
            elif self.direction == 'payment_request_revoke':
                if payment_request:
                    payment_request._revoke_misa_payment_request()
                else:
                    raise ValueError('payment_request_revoke job thiếu payment_request_id')
            elif self.direction == 'incoming':
                pick._sync_incoming_po_to_misa()
            elif self.direction == 'outgoing':
                pick._sync_outgoing_so_to_misa()
            elif self.direction == 'sa_invoice':
                if so:
                    so._sync_sa_invoice_to_misa()
                else:
                    raise ValueError('sa_invoice job thiếu sale_order_id')
            self.write({
                'status': 'done',
                'error_msg': False,
                'processed_at': fields.Datetime.now(),
            })
        except Exception as e:
            if self.direction in ('purchase_order', 'purchase_order_revoke') and po:
                error_text = str(e)[:2000]
                po_state = 'error'
                if self.direction == 'purchase_order_revoke' and (
                    'IsCreatedVoucher' in error_text or 'Đã sinh chứng từ' in error_text
                ):
                    po_state = 'manual_delete_required'
                po.with_context(skip_misa_purchase_order_lifecycle=True).sudo().write({
                    'misa_purchase_order_state': po_state,
                    'misa_purchase_order_last_error': error_text,
                    'misa_purchase_order_state_updated_at': fields.Datetime.now(),
                })
            if self.direction in ('payment_request', 'payment_request_revoke') and payment_request:
                error_text = str(e)[:2000]
                payment_state = 'error'
                if self.direction == 'payment_request_revoke' and (
                    'IsCreatedVoucher' in error_text or 'Đã sinh chứng từ' in error_text
                ):
                    payment_state = 'manual_delete_required'
                payment_request.sudo().write({
                    'state': payment_state,
                    'error_msg': error_text,
                    'state_updated_at': fields.Datetime.now(),
                })
            self.write({
                'retry_count': self.retry_count + 1,
                'error_msg': str(e)[:2000],
                'processed_at': fields.Datetime.now(),
                'status': 'error' if self.retry_count + 1 >= MAX_RETRY else 'pending',
            })
            _logger.exception('AMIS sync job %d failed (retry %d/%d)', self.id, self.retry_count, MAX_RETRY)

    def action_retry(self):
        """Nút retry thủ công từ UI."""
        for job in self:
            job.write({'status': 'pending', 'retry_count': 0, 'error_msg': False})
        return True

    def action_run_now(self):
        """Chạy ngay job này trong cursor riêng (không cần đợi cron)."""
        import odoo
        for job in self:
            if job.status not in ('pending', 'error'):
                continue
            try:
                with odoo.registry(self.env.cr.dbname).cursor() as cr:
                    env = odoo.api.Environment(cr, self.env.uid, {})
                    j = env['amis.sync.job'].browse(job.id)
                    # Reset trong cursor riêng — tránh SerializationFailure
                    j.write({'status': 'pending', 'retry_count': 0, 'error_msg': False})
                    j._execute()
                    cr.commit()
            except Exception:
                _logger.exception('AMIS sync job %d: action_run_now failed', job.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
