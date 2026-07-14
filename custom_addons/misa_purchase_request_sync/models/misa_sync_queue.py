# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class MisaSyncQueue(models.Model):
    _name = "misa.sync.queue"
    _description = "MISA Sync Queue"
    _order = "sequence asc, id asc"

    name = fields.Char(string="Mã Đơn (MISA)", required=True, index=True)
    misa_id = fields.Char(string="MISA ID", index=True)
    sync_type = fields.Selection([
        ('pr', 'Purchase Request'),
        ('so', 'Sale Order'),
        ('po', 'Purchase Order')
    ], string="Loại đồng bộ", required=True)
    
    payload = fields.Text(string="JSON Payload", required=True)
    
    state = fields.Selection([
        ('draft', 'Đang chờ (Pending)'),
        ('processing', 'Đang xử lý (Processing)'),
        ('done', 'Thành công (Done)'),
        ('failed', 'Lỗi (Failed)')
    ], string="Trạng thái", default='draft', required=True, index=True)
    
    retry_count = fields.Integer(string="Số lần thử lại", default=0)
    error_log = fields.Text(string="Chi tiết lỗi")
    sequence = fields.Integer(string="Ưu tiên", default=10, index=True)
    processing_started_at = fields.Datetime(string="Bắt đầu xử lý lúc", index=True)

    def _recover_zombie_records(self):
        """
        Recover records that have been in 'processing' state for too long (e.g. > 10 minutes).
        This can happen if the Odoo worker is killed or crashes without updating the state.
        """
        timeout_minutes = 10
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=timeout_minutes)
        zombies = self.search([
            ('state', '=', 'processing'),
            ('processing_started_at', '<', cutoff)
        ])
        if zombies:
            _logger.warning("MISA Sync Queue: Found %d zombie processing records: %s", len(zombies), zombies.mapped('name'))
            for z in zombies:
                z.retry_count += 1
                if z.retry_count >= 3:
                    z.write({
                        'state': 'failed',
                        'error_log': _("Timeout: Kẹt ở trạng thái processing quá %s phút.") % timeout_minutes
                    })
                else:
                    z.write({
                        'state': 'draft',
                        'error_log': _("Auto-recovered: Kẹt ở trạng thái processing quá %s phút. Đang chờ thử lại (lần thứ %s).") % (timeout_minutes, z.retry_count),
                        'sequence': z.sequence + 10  # Đẩy xuống cuối hàng
                    })
            self.env.cr.commit()

    @api.model
    def process_queue(self, limit=20):
        """
        Cron job processing
        """
        # Determine records to process
        if self:
            # Called on a specific recordset (e.g. retry button from form view)
            records = self.filtered(lambda r: r.state in ('draft', 'failed'))
            if records:
                records.write({
                    'state': 'processing',
                    'processing_started_at': fields.Datetime.now(),
                    'error_log': False
                })
                self.env.cr.commit()
        else:
            # Auto-recovery for stuck records
            self._recover_zombie_records()

            # Find draft records using SELECT FOR UPDATE SKIP LOCKED to prevent race conditions
            self.env.cr.execute("""
                SELECT id FROM misa_sync_queue
                WHERE state = 'draft'
                ORDER BY sequence ASC, id ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            """, [limit])
            ids = [row[0] for row in self.env.cr.fetchall()]
            records = self.browse(ids)
            
            if records:
                records.write({
                    'state': 'processing',
                    'processing_started_at': fields.Datetime.now()
                })
                self.env.cr.commit()

        # Process each record
        for record in records:
            try:
                # Dùng savepoint để cô lập lỗi DB (FK violation, ...)
                # Nếu lỗi xảy ra, savepoint rollback nhưng transaction chính vẫn sống
                with self.env.cr.savepoint():
                    payload_dict = json.loads(record.payload)
                    if record.sync_type == 'pr':
                        self._process_pr(record, payload_dict)
                    elif record.sync_type == 'so':
                        self._process_so(record, payload_dict)
                    elif record.sync_type == 'po':
                        self._process_po(record, payload_dict)
                
                # Nếu không exception tức là thành công
                record.write({
                    'state': 'done',
                    'error_log': False
                })
                self.env.cr.commit()

            except Exception as e:
                _logger.exception("Lỗi khi xử lý queue %s (ID: %s)", record.name, record.id)
                # Transaction vẫn sống vì savepoint đã rollback lỗi DB
                record.retry_count += 1
                if record.retry_count >= 3:
                    record.write({
                        'state': 'failed',
                        'error_log': str(e)
                    })
                else:
                    record.write({
                        'state': 'draft',
                        'error_log': str(e),
                        'sequence': record.sequence + 10  # Đẩy xuống cuối hàng
                    })
                self.env.cr.commit()

    def _process_pr(self, queue_record, payload):
        """
        Giao tiếp nội bộ: Xử lý PR Create Payload
        Ta có thể sử dụng lại logic của api_extension_pr_create.
        """
        # Trích xuất logic tạo PR vào trong này, hoặc gọi đến hàm helper của module
        # Vì model không truy cập trực tiếp Controller, ta nên chuyển logic
        # từ Controller `api_extension_pr_create` sang một hàm của model `purchase.request`.
        # Tạm thời để gọi hàm model.
        self.env['purchase.request'].sudo().api_create_from_misa_payload(payload)

    def _process_so(self, queue_record, payload):
        """
        Giao tiếp nội bộ: Xử lý SO Resync
        """
        misa_order_id = payload.get("misa_order_id")
        warehouse_id = payload.get("warehouse_id")
        create_when_missing = payload.get("create_when_missing", True)
        
        self.env["sale.order"].sudo().api_resync_by_misa(
            misa_order_id=misa_order_id,
            warehouse_id=warehouse_id,
            create_when_missing=create_when_missing,
        )

    def _process_po(self, queue_record, payload):
        po_code = payload.get("po_code") or queue_record.name
        create_when_missing = payload.get("create_when_missing", True)
        delete_when_missing = payload.get("delete_when_missing", True)

        result = self.env["purchase.order"].sudo().api_sync_po_by_code(
            po_code=po_code,
            create_when_missing=create_when_missing,
            delete_when_missing=delete_when_missing,
        )
        if not result or not result.get("ok"):
            raise Exception(
                (result or {}).get("message")
                or (result or {}).get("detail")
                or str(result)
            )
        queue_record.write({"error_log": json.dumps(result, ensure_ascii=False)})
