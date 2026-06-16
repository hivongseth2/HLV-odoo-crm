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
    direction = fields.Selection([
        ('purchase_order', 'Đơn mua hàng (pu_order)'),
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
            # Mỗi job dùng cursor riêng để tránh 1 HTTP timeout làm block cả batch
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
        try:
            if self.direction == 'purchase_order':
                if po:
                    po._sync_purchase_order_to_misa()
                else:
                    raise ValueError('purchase_order job thieu purchase_order_id')
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
        return True
