# -*- coding: utf-8 -*-
import logging
import re
import uuid
from datetime import datetime

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ZERO_UUID = '00000000-0000-0000-0000-000000000000'


class StockPickingAmisSync(models.Model):
    _inherit = 'stock.picking'

    misa_inward_synced = fields.Boolean(
        string='Đã đồng bộ phiếu nhập MISA',
        default=False,
        copy=False,
    )
    misa_inward_org_refid = fields.Char(
        string='MISA org_refid phiếu nhập',
        copy=False,
    )
    misa_outward_org_refid = fields.Char(
        string='MISA org_refid phiếu xuất kho',
        copy=False,
    )

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            try:
                if picking.picking_type_code in ('incoming', 'outgoing'):
                    picking._enqueue_misa_sync(picking.picking_type_code)
            except Exception:
                _logger.exception('AMIS enqueue failed for picking %s', picking.name)
            try:
                picking._maybe_auto_draft_meinvoice()
            except Exception:
                _logger.exception('meInvoice auto-draft check failed for picking %s', picking.name)
        return res

    # ── meInvoice: auto-create draft on picking done ──────────────────────────

    _STEP_KEYWORDS = {
        'pick': ('pick',),
        'pack': ('pack',),
        'out':  ('out', 'ship', 'delivery'),  # WH/OUT, WH/SHIP, v.v.
    }

    def _get_picking_step(self):
        """Nhận diện bước pick / pack / out dựa vào sequence_code của picking type.

        Trả về 'pick', 'pack', 'out', hoặc None nếu không khớp.
        """
        self.ensure_one()
        if self.picking_type_code != 'outgoing' and self.picking_type_code != 'internal':
            return None
        seq = (self.picking_type_id.sequence_code or '').lower()
        for step, keywords in self._STEP_KEYWORDS.items():
            if any(kw in seq for kw in keywords):
                return step
        # Fallback: nếu code là outgoing và không có bước nào → coi là 'out'
        if self.picking_type_code == 'outgoing':
            return 'out'
        return None

    def _maybe_auto_draft_meinvoice(self):
        """Tạo hóa đơn nháp meInvoice nếu picking này đúng bước cấu hình."""
        self.ensure_one()
        if self.state != 'done':
            return

        config = self.env['amis.callback.config'].sudo().search([], limit=1)
        if not config or not config.meinvoice_auto_draft_on_confirm:
            return

        trigger_step = config.meinvoice_draft_trigger_step or 'out'
        if trigger_step == 'confirm':
            return  # handled by action_confirm

        picking_step = self._get_picking_step()
        if picking_step != trigger_step:
            return

        # Lấy sale order liên quan
        so = self._get_related_sales_order()
        if not so:
            return

        if not getattr(so, 'shopee_order_ref', None):
            return  # chỉ xử lý đơn Shopee

        so.sudo()._auto_create_shopee_meinvoice_draft()

    def _enqueue_misa_sync(self, direction):
        """Tạo job trong hàng đợi amis.sync.job thay vì push trực tiếp."""
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        enabled = (config.sync_incoming_po_enabled if direction == 'incoming'
                   else config.sync_outgoing_so_enabled)
        if not enabled:
            return

        so = None
        if direction == 'outgoing':
            so = self._get_related_sales_order()
            # Không enqueue nếu SO đã sync SAVoucher thành công
            if so and so.misa_sa_voucher_synced:
                _logger.info(
                    'Skip enqueue outgoing for picking %s: SO %s đã sync SAVoucher rồi.',
                    self.name, so.name,
                )
                return
            # Không enqueue nếu SO đã có job outgoing đang pending/done/error
            if so:
                so_job = self.env['amis.sync.job'].sudo().search([
                    ('sale_order_id', '=', so.id),
                    ('direction', '=', 'outgoing'),
                    ('status', 'in', ('pending', 'done')),
                ], limit=1)
                if so_job:
                    _logger.info(
                        'Skip enqueue outgoing for picking %s: SO %s đã có job outgoing (status=%s).',
                        self.name, so.name, so_job.status,
                    )
                    return

        # Tránh tạo job trùng nếu picking đã được enqueue và chưa xử lý
        existing = self.env['amis.sync.job'].sudo().search([
            ('picking_id', '=', self.id),
            ('direction', '=', direction),
            ('status', '=', 'pending'),
        ], limit=1)
        if existing:
            return

        vals = {
            'picking_id': self.id,
            'direction': direction,
            'status': 'pending',
        }
        if so:
            vals['sale_order_id'] = so.id

        self.env['amis.sync.job'].sudo().create(vals)
        _logger.info('AMIS sync job enqueued for picking %s (%s)', self.name, direction)


    def action_test_outgoing_push(self):
        """Action de test manual push outgoing picking len MISA (chi dung khi da done)"""
        self.ensure_one()
        if self.state != 'done':
            raise UserError('Phiếu phải ở trạng thái "Hoàn thành" trước khi đẩy lên MISA.')
        self._enqueue_misa_sync('outgoing')
        return True

    def _sync_incoming_po_to_misa(self):
        self.ensure_one()
        if self.state != 'done' or self.picking_type_code != 'incoming':
            return

        if self.misa_inward_synced:
            _logger.info('Skip incoming sync for %s: already synced to MISA.', self.name)
            return

        purchase_order = self._get_related_purchase_order()
        if not purchase_order:
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.sync_incoming_po_enabled:
            return

        if not config.ensure_sync_ready():
            return

        purchase_order._misa_refresh_purchase_order_refs_from_logs()
        purchase_lines = self.move_ids_without_package.mapped('purchase_line_id')
        purchase_order_refid = purchase_order._misa_purchase_order_link_refid()
        if config.sync_purchase_order_enabled and not purchase_order._is_misa_imported_purchase_order():
            missing_detail_lines = purchase_order._misa_purchase_order_lines_missing_ref_detail(purchase_lines)
            purchase_order_refid = purchase_order._misa_purchase_order_link_refid()
            if not purchase_order.misa_purchase_order_synced or not purchase_order_refid or missing_detail_lines:
                purchase_order._enqueue_misa_purchase_order(raise_on_skip=False, force=True)
                missing_names = ', '.join(missing_detail_lines.mapped('product_id.display_name'))
                if not purchase_order.misa_purchase_order_synced:
                    reason = 'callback thanh cong don mua'
                elif not purchase_order_refid:
                    reason = 'refid/org_refid don mua'
                else:
                    reason = 'ref_detail_id dong: %s' % missing_names
                raise UserError(
                    'Don mua hang %s chua co %s MISA thuc te; da enqueue don mua, phieu nhap se retry sau callback.'
                    % (purchase_order.name, reason)
                )

        if not purchase_order_refid:
            raise UserError(
                'Don mua hang %s chua co refid/org_refid MISA de lien ket phieu nhap.'
                % purchase_order.name
            )

        voucher_payload, dictionary_items, reference_items = self._prepare_misa_inward_payload(config, purchase_order)
        org_refid = voucher_payload.get('org_refid')
        _logger.info(
            'Push MISA inward %s: org_refid=%s, po=%s, detail_po_refid=%s, detail_links=%s',
            self.name,
            org_refid,
            purchase_order.name,
            voucher_payload.get('detail') and voucher_payload['detail'][0].get('pu_order_refid') or '',
            ', '.join(
                '%s qty=%s inward_detail=%s po_detail=%s' % (
                    detail.get('inventory_item_code') or detail.get('inventory_item_name') or '',
                    detail.get('quantity') or 0.0,
                    detail.get('ref_detail_id') or '',
                    detail.get('pu_order_ref_detail_id') or '',
                )
                for detail in voucher_payload.get('detail') or []
            ),
        )

        if dictionary_items:
            config.push_dictionary(dictionary_items)
            _logger.info(
                'Created %d MISA dictionary items before inward picking %s sync...',
                len(dictionary_items), self.name,
            )
        config.push_inward_voucher(voucher_payload, dictionary_items=[], reference_items=reference_items)

        self.sudo().write({
            'misa_inward_org_refid': org_refid or '',
        })

    def _get_related_purchase_order(self):
        self.ensure_one()
        po = self.move_ids_without_package.mapped('purchase_line_id.order_id')[:1]
        if po:
            return po
        if self.origin:
            return self.env['purchase.order'].sudo().search([('name', '=', self.origin)], limit=1)
        return self.env['purchase.order']

    def _sync_outgoing_so_to_misa(self):
        """Push SAVoucher (bán hàng kiêm xuất kho, voucher_type=13) lên MISA."""
        self.ensure_one()
        if self.state != 'done' or self.picking_type_code != 'outgoing':
            return

        sales_order = self._get_related_sales_order()
        if not sales_order:
            _logger.info('Skip outgoing sync for %s: không tìm được đơn bán hàng.', self.name)
            return

        # Lọc theo cấu hình: chỉ sync đơn Shopee hoặc tất cả đơn
        has_shopee_ref = bool(getattr(sales_order, 'shopee_order_ref', None))
        if config.sync_shopee_only and not has_shopee_ref:
            _logger.info('Skip outgoing sync for %s: đơn %s không có shopee_order_ref (chế độ chỉ sync Shopee).', self.name, sales_order.name)
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.sync_outgoing_so_enabled:
            return

        if not config.ensure_sync_ready():
            return

        # Bỏ qua nếu đã sync SAVoucher
        if sales_order.misa_sa_voucher_synced:
            _logger.info('Skip outgoing sync for %s: đơn %s đã sync SAVoucher.', self.name, sales_order.name)
            return

        # Kiểm tra sản phẩm chưa map MISA — bỏ qua đơn và raise lỗi rõ ràng
        moves_to_sync = self.move_ids_without_package.filtered(lambda m: m.quantity > 0)
        unmapped = [
            m.product_id.display_name
            for m in moves_to_sync
            if not (m.product_id.misa_inventory_item_id or '').strip()
        ]
        if unmapped:
            raise UserError(
                'Đơn hàng "%s" có sản phẩm chưa map với MISA, bỏ qua đồng bộ:\n%s\n\n'
                'Hệ thống sẽ tự động map lại sau 30 phút. '
                'Hoặc bấm "Đồng bộ sản phẩm mới" trong Cấu hình AMIS rồi retry job này.'
                % (sales_order.name, '\n'.join('• ' + n for n in unmapped))
            )

        voucher_payload = self._prepare_misa_sa_voucher_payload(config, sales_order)
        org_refid = voucher_payload.get('org_refid', '')

        import json
        _logger.info(
            'SAVoucher payload for %s:\n%s',
            self.name,
            json.dumps(voucher_payload, ensure_ascii=False, default=str, indent=2),
        )

        result = config.push_sa_voucher(voucher_payload)
        _logger.info(
            'SAVoucher MISA response for %s: Success=%s ErrorCode=%s ErrorMessage=%s',
            self.name,
            result.get('Success') if isinstance(result, dict) else result,
            (result or {}).get('ErrorCode', ''),
            (result or {}).get('ErrorMessage', ''),
        )

        sales_order.sudo().write({
            'misa_sa_voucher_synced': True,
            'misa_sa_voucher_org_refid': org_refid,
        })
        _logger.info('SAVoucher synced for SO %s (picking %s), org_refid=%s', sales_order.name, self.name, org_refid)

    def _prepare_misa_sa_voucher_payload(self, config, sales_order):
        """Chuẩn bị payload SAVoucher (voucher_type=13) kèm in_outward (voucher_type=8)."""
        self.ensure_one()
        partner = self.partner_id or sales_order.partner_id

        branch_id = (config.misa_branch_id or '').strip()
        stock_id = (config.misa_stock_id or '').strip()

        if not branch_id:
            raise UserError('Thiếu MISA Branch ID trong cấu hình.')
        if not stock_id:
            raise UserError('Thiếu MISA Stock ID trong cấu hình.')

        # Resolve account_object qua config (logic chung với SAInvoice)
        account_object_id, account_object_code, account_object_name = \
            config.resolve_misa_account_object(partner, sale_order=sales_order)

        # Dùng org_refid từ SO nếu đã có (idempotent), hoặc sinh mới bằng uuid4 và persist ngay
        sa_voucher_refid = (sales_order.misa_sa_voucher_org_refid or '').strip()
        if not sa_voucher_refid:
            sa_voucher_refid = str(uuid.uuid4())
            sales_order.sudo().write({'misa_sa_voucher_org_refid': sa_voucher_refid})

        # outward_refid: dùng refid đã lưu hoặc sinh mới (mỗi sync mới = refid mới để MISA tạo lại detail)
        outward_refid = (self.misa_outward_org_refid or '').strip()
        if not outward_refid:
            outward_refid = str(uuid.uuid4())
            self.sudo().write({'misa_outward_org_refid': outward_refid})

        # Pre-calculate SAInvoice refid (deterministic từ SO.id) để link 2 chiều
        sa_invoice_refid_link = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'sa_invoice|%d' % sales_order.id))

        detail = []
        total_gross = 0.0
        total_discount = 0.0
        total_sale = 0.0
        total_vat = 0.0

        for idx, move in enumerate(
            self.move_ids_without_package.filtered(lambda m: m.quantity > 0), start=1
        ):
            product = move.product_id
            qty_done = float(move.quantity)

            sale_line = move.sale_line_id
            price_unit_after_tax = float(sale_line.price_unit) if sale_line else 0.0  # Đơn giá có thuế (Odoo lưu)
            discount = float(sale_line.discount) if sale_line and sale_line.discount else 0.0

            vat_rate = 0.0
            if sale_line:
                for tax in sale_line.tax_id:
                    if tax.amount_type == 'percent':
                        vat_rate = float(tax.amount)
                        break

            # Sản phẩm khuyến mãi: price_subtotal = 0 → tất cả giá trị = 0
            is_promo = sale_line and float(sale_line.price_subtotal) == 0.0

            # Đơn giá trước thuế = Đơn giá có thuế / (1 + thuế suất)
            price_before_tax = price_unit_after_tax / (1.0 + vat_rate / 100.0) if vat_rate else price_unit_after_tax
            # Đơn giá theo đơn vị chính (main_unit_price) = giá trước thuế
            main_unit_price = round(price_before_tax, 2)

            if is_promo:
                price_before_tax = 0.0
                main_unit_price = 0.0
                amount_oc = 0.0
                discount_amount_line = 0.0
                net_amount = 0.0
                vat_amount = 0.0
            else:
                # Thành tiền = đơn giá trước thuế * số lượng (trước CK, trước thuế)
                amount_oc = round(qty_done * price_before_tax, 2)
                # Tiền CK = amount_oc * % CK
                discount_amount_line = round(amount_oc * discount / 100.0, 2)
                net_amount = amount_oc - discount_amount_line

                # Thuế tính trên (Thành tiền - Tiền CK)
                vat_amount = round(net_amount * vat_rate / 100.0, 2)

            total_gross += amount_oc
            total_discount += discount_amount_line
            total_sale += net_amount
            total_vat += vat_amount

            inventory_item_id = (product.misa_inventory_item_id or '').strip()
            unit_id = (move.product_uom.misa_unit_id or '').strip()
            # Không gọi get_dictionary lúc sync (tránh 429). MISA match theo inventory_item_code nếu id trống.

            ref_detail_id = self._misa_move_ref_detail_id(move, 'sa_v_detail')

            detail.append({
                'ref_detail_id': ref_detail_id,
                'refid': sa_voucher_refid,
                'inventory_item_id': inventory_item_id,
                'unit_id': unit_id,
                'main_unit_id': unit_id,
                'stock_id': stock_id,
                'account_object_id': account_object_id,
                'sort_order': idx,
                'is_promotion': is_promo,
                'un_resonable_cost': False,
                'not_in_vat_declaration': False,
                'quantity': qty_done,
                'unit_price': price_before_tax,
                'unit_price_after_tax': price_unit_after_tax if not is_promo else 0.0,
                'main_unit_price': main_unit_price,
                'unit_price_after_discount': round(price_before_tax * (1.0 - discount / 100.0), 2) if not is_promo else 0.0,
                'amount_oc': amount_oc,
                'amount': amount_oc,
                'discount_rate': discount if not is_promo else 0.0,
                'discount_amount_oc': discount_amount_line,
                'discount_amount': discount_amount_line,
                'vat_rate': vat_rate if not is_promo else 0.0,
                'vat_amount_oc': vat_amount,
                'vat_amount': vat_amount,
                'main_convert_rate': 1.0,
                'main_quantity': qty_done,
                'amount_after_tax': 0.0,
                'invoiced_quantity': qty_done,
                'main_invoiced_quantity': 0.0,
                'export_tax_rate': 0.0,
                'export_tax_amount': 0.0,
                'description': re.sub(r'^\[.*?\]\s*', '', product.name or ''),
                'debit_account': '131',
                'credit_account': '5111',
                'vat_account': '3331',
                'exchange_rate_operator': '*',
                'vat_description': 'Thue GTGT - %s' % re.sub(r'^\[.*?\]\s*', '', product.name or ''),
                'account_object_name': account_object_name,
                'account_object_code': account_object_code,
                'account_object_address': partner.contact_address_complete if partner else '',
                'inventory_item_code': product.default_code or str(product.id),
                'inventory_item_type': 0,
                'unit_name': move.product_uom.name,
                'main_unit_name': move.product_uom.name,
                'stock_code': 'HLV',
                'stock_name': 'HLV',
                'inventory_item_name': re.sub(r'^\[.*?\]\s*', '', product.name or ''),
                'is_follow_serial_number': False,
                'is_allow_duplicate_serial_number': False,
                'is_unit_price_after_tax': False,
                'is_description': False,
                'is_description_import': False,
                'discount_type': 0,
                'exported_invoice_at_least_one': False,
                'inventory_resale_type_id': 0,
                'return_quantity': 0.0,
                'is_un_update_outward_price': False,
                'state': 0,
            })

        total_sale = round(total_sale, 2)
        total_discount = round(total_discount, 2)
        total_vat = round(total_vat, 2)
        total_amount = round(total_sale + total_vat, 2)
        refdate = self._to_misa_date(self.date_done)
        shopee_ref = getattr(sales_order, 'shopee_order_ref', '') or ''

        # Build in_outward_detail: dùng giá vốn (move.price_unit = standard cost)
        outward_detail = []
        for idx, move in enumerate(
            self.move_ids_without_package.filtered(lambda m: m.quantity > 0), start=1
        ):
            product = move.product_id
            qty_done = float(move.quantity)
            cost_price = float(move.price_unit or 0.0)  # giá vốn (standard/average cost)
            if cost_price == 0.0:
                cost_price = float(move.product_id.standard_price or 0.0)
            cost_amount = qty_done * cost_price

            # Giá bán từ sale line
            sale_line = move.sale_line_id
            sale_price_unit = float(sale_line.price_unit) if sale_line else 0.0
            sale_discount = float(sale_line.discount or 0.0) if sale_line else 0.0
            sale_amount_line = qty_done * sale_price_unit * (1.0 - sale_discount / 100.0)

            inventory_item_id = (product.misa_inventory_item_id or '').strip()
            unit_id = (move.product_uom.misa_unit_id or '').strip()

            ref_outward_detail_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'outward_detail|%d|%d' % (self.id, move.id)))
            # Link về dòng chi tiết SAVoucher tương ứng
            sa_v_ref_detail_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'sa_v_detail|%d|%d' % (self.id, move.id)))

            outward_detail.append({
                'ref_detail_id': ref_outward_detail_id,
                'refid': outward_refid,
                'inventory_item_id': inventory_item_id,
                'unit_id': unit_id,
                'main_unit_id': unit_id,
                'stock_id': stock_id,
                'sort_order': idx,
                'quantity': qty_done,
                'unit_price_finance': cost_price,
                'unit_price_management': cost_price,
                'main_unit_price_finance': cost_price,
                'amount_finance': cost_amount,
                'amount_management': cost_amount,
                'sale_price': sale_price_unit,
                'sale_amount': sale_amount_line,
                'main_convert_rate': 1.0,
                'main_quantity': qty_done,
                'debit_account': '632',
                'credit_account': '1561',
                'exchange_rate_operator': '*',
                'inventory_item_code': product.default_code or str(product.id),
                'inventory_item_name': re.sub(r'^\[.*?\]\s*', '', product.name or ''),
                'unit_name': move.product_uom.name,
                'main_unit_name': move.product_uom.name,
                'stock_code': 'HLV',
                'stock_name': 'HLV',
                'description': re.sub(r'^\[.*?\]\s*', '', product.name or ''),
                'account_object_id': account_object_id,
                'account_object_code': account_object_code,
                'account_object_name': account_object_name,
                'sa_voucher_refid': sa_voucher_refid,
                'sa_voucher_ref_detail_id': sa_v_ref_detail_id,
                'is_promotion': False,
                'is_un_update_outward_price': False,
                'inventory_resale_type_id': 0,
                'un_resonable_cost': False,
                'is_description': False,
                'state': 0,
            })

        total_cost = sum(d.get('amount_finance', 0.0) for d in outward_detail)

        in_outward = {
            'voucher_type': 8,
            'is_get_new_id': True,
            'is_allow_group': False,
            'org_reftype': 0,
            'act_voucher_type': 0,
            'total_amount': total_cost,
            'refid': outward_refid,
            'account_object_id': account_object_id,
            'branch_id': branch_id,
            'from_stock_id': stock_id,
            'display_on_book': 0,
            'reforder': int(datetime.utcnow().timestamp() * 1000),
            'refdate': refdate,
            'posted_date': refdate,
            'is_posted_finance': False,
            'is_posted_management': False,
            'is_posted_inventory_book_finance': False,
            'is_posted_inventory_book_management': False,
            'is_branch_issued': False,
            'is_sale_with_outward': True,
            'is_invoice_replace': False,
            'total_amount_finance': total_cost,
            'total_amount_management': total_cost,
            'refno_finance': '',
            'refno_management': '',
            'account_object_name': account_object_name,
            'account_object_code': account_object_code,
            'account_object_address': partner.contact_address_complete if partner else '',
            'journal_memo': 'Xuat kho ban hang %s (Odoo: %s)' % (sales_order.name, self.name),
            'reftype': 2020,
            'is_executed': False,
            'publish_status': 0,
            'is_invoice_deleted': False,
            'invoice_status': 0,
            'is_invoice_receipted': False,
            'is_reject_handler': False,
            'auto_refno': False,
            'state': 0,
            'detail': outward_detail,
        }

        voucher = {
            'voucher_type': 13,
            'is_get_new_id': True,
            'org_refid': sa_voucher_refid,
            'is_allow_group': False,
            'org_refno': sales_order.name,
            'org_reftype': 3530,
            'org_reftype_name': 'Ban hang',
            'refno': '',
            'act_voucher_type': 0,
            'refid': sa_voucher_refid,
            'branch_id': branch_id,
            'account_object_id': account_object_id,
            'display_on_book': 0,
            'outward_exported_status': 1,
            'debt_status': 0,
            'reforder': int(datetime.utcnow().timestamp() * 1000),
            'discount_rate_voucher': 0.0,
            'refdate': refdate,
            'posted_date': refdate,
            'inv_date': refdate,
            'is_posted_finance': False,
            'is_posted_management': False,
            'include_invoice': 0,
            'include_invoice_import': False,
            'is_invoice_exported': False,
            'is_paid': False,
            'is_sale_with_outward': True,
            'is_invoice_exported_last_year': False,
            'exchange_rate': 1.0,
            'total_sale_amount_oc': round(total_gross, 2),
            'total_sale_amount': round(total_gross, 2),
            'total_amount_oc': total_amount,
            'total_amount': total_amount,
            'total_discount_amount_oc': total_discount,
            'total_discount_amount': total_discount,
            'total_vat_amount_oc': total_vat,
            'total_vat_amount': total_vat,
            'total_export_tax_amount': 0.0,
            'refno_finance': '',
            'refno_management': '',
            'account_object_name': account_object_name,
            'account_object_code': account_object_code,
            'account_object_address': partner.contact_address_complete if partner else '',
            'account_object_tax_code': (partner.vat or '') if partner else '',
            'journal_memo': 'Ban hang %s (Shopee: %s) (Odoo: %s)' % (sales_order.name, shopee_ref, self.name),
            'currency_id': sales_order.currency_id.name or 'VND',
            'discount_type': 1,
            'paid_type': 0,
            'publish_status': 0,
            'send_email_status': 0,
            'is_remind_debt': True,
            'is_un_limit': False,
            'outward_refid': outward_refid,
            'sa_invoice_refid': sa_invoice_refid_link,
            'reftype': 3530,
            'auto_refno': False,
            'state': 0,
            'detail': detail,
            'in_outward': in_outward,
        }
        return voucher

    def _get_related_sales_order(self):
        self.ensure_one()
        # Tim SO tu sale_line_id (Many2one tren stock.move)
        so = self.move_ids_without_package.mapped('sale_line_id.order_id')[:1]
        if so:
            return so
        # Tim theo origin (ten SO)
        if self.origin:
            return self.env['sale.order'].sudo().search([('name', '=', self.origin)], limit=1)
        return self.env['sale.order']

    def _to_misa_date(self, value):
        if not value:
            value = datetime.utcnow()
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d')
        return str(value)[:10]

    def _prepare_misa_inward_payload(self, config, purchase_order):
        self.ensure_one()
        partner = self.partner_id or purchase_order.partner_id
        if not partner:
            raise UserError('Phieu nhap "%s" thieu nha cung cap.' % self.name)

        refid = (self.misa_inward_org_refid or '').strip()
        if not refid:
            refid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_inward|%d' % self.id))
            self.sudo().write({'misa_inward_org_refid': refid})

        branch_id = (config.misa_branch_id or '').strip()
        stock_id = (config.misa_stock_id or '').strip()
        if not branch_id:
            raise UserError('Thieu MISA Branch ID trong cau hinh.')
        if not stock_id:
            raise UserError('Thieu MISA Stock ID trong cau hinh.')

        dictionary_items = []
        account_object = purchase_order._ensure_misa_account_object(config, partner, dictionary_items)
        account_object_id = account_object.get('account_object_id') or ''
        account_object_code = account_object.get('account_object_code') or purchase_order._misa_partner_code(partner)
        account_object_name = account_object.get('account_object_name') or partner.display_name or partner.name or ''
        if not account_object_id:
            raise UserError('Khong tao/tim duoc MISA Account Object cho nha cung cap: %s' % partner.display_name)

        # Kho MISA hien tai co dinh theo cau hinh kho HLV.
        misa_warehouse_code = 'HLV'

        pu_order_refid = purchase_order._misa_purchase_order_link_refid()
        if not pu_order_refid:
            raise UserError('Don mua hang %s chua co org_refid MISA de lien ket phieu nhap.' % purchase_order.name)

        moves = self.move_ids_without_package.filtered(lambda m: m.quantity > 0)
        if not moves:
            raise UserError('Phieu nhap "%s" khong co dong da nhap de sync MISA.' % self.name)

        detail = []
        total_amount = 0.0
        total_vat_amount = 0.0

        for idx, move in enumerate(moves, start=1):
            product = move.product_id
            purchase_line = move.purchase_line_id
            if not purchase_line:
                raise UserError('Dong nhap kho %s khong lien ket voi dong don mua hang.' % move.display_name)
            qty_done = float(move.quantity or 0.0)
            price_unit = float(purchase_line.price_unit or 0.0)
            amount = qty_done * price_unit
            taxes = purchase_line.taxes_id.filtered(lambda t: t.amount_type == 'percent')
            vat_rate = float(taxes[0].amount or 0.0) if taxes else 0.0
            vat_amount = amount * vat_rate / 100.0
            total_amount += amount
            total_vat_amount += vat_amount
            pu_order_ref_detail_id = purchase_order._misa_purchase_order_line_ref_detail_id(purchase_line)
            if not pu_order_ref_detail_id:
                raise UserError(
                    'Dong don mua %s/%s chua co ref_detail_id MISA thuc te de lien ket phieu nhap.'
                    % (purchase_order.name, purchase_line.product_id.display_name)
                )

            unit = purchase_order._ensure_misa_unit(config, move.product_uom, dictionary_items)
            inventory_item = purchase_order._ensure_misa_inventory_item(
                config, product, move.product_uom, unit, price_unit, dictionary_items
            )
            inventory_item_id = inventory_item.get('inventory_item_id') or ''
            inventory_item_code = inventory_item.get('inventory_item_code') or product.default_code or str(product.id)
            inventory_item_name = inventory_item.get('inventory_item_name') or product.display_name
            unit_id = unit.get('unit_id') or ''
            unit_name = unit.get('unit_name') or move.product_uom.name
            unit_values = purchase_order._misa_document_unit_values(
                config, inventory_item, move.product_uom, unit, qty_done, price_unit
            )
            if not inventory_item_id:
                raise UserError('Khong tao/tim duoc MISA Inventory Item cho san pham: %s' % product.display_name)
            if not unit_id:
                raise UserError('Khong tao/tim duoc MISA Unit cho don vi tinh: %s' % move.product_uom.name)

            ref_detail_id = self._misa_move_ref_detail_id(move, 'misa_inward_detail')

            # Tai khoan co dinh theo yeu cau: Kho 1561, Cong no 331.
            debit_account = '1561'
            credit_account = '331'

            detail.append({
                'ref_detail_id': ref_detail_id,
                'refid': refid,
                'inventory_item_id': inventory_item_id,
                'stock_id': stock_id,
                'unit_id': unit_values['unit_id'],
                'main_unit_id': unit_values['main_unit_id'],
                'account_object_id': account_object_id,
                'sort_order': idx,
                'inventory_resale_type_id': 0,
                'un_resonable_cost': False,
                'is_promotion': False,
                'quantity': qty_done,
                'unit_price': price_unit,
                'main_unit_price': unit_values['main_unit_price'],
                'unit_price_after_tax': price_unit * (1.0 + vat_rate / 100.0),
                'unit_price_finance': price_unit,
                'amount_finance': amount,
                'amount': amount,
                'amount_oc': amount,
                'vat_rate': vat_rate,
                'vat_amount': vat_amount,
                'vat_amount_oc': vat_amount,
                'amount_after_tax': amount + vat_amount,
                'inward_amount': amount,
                'inward_amount_oc': amount,
                'discount_rate': 0.0,
                'discount_amount': 0.0,
                'discount_amount_oc': 0.0,
                'unit_price_management': price_unit,
                'amount_management': amount,
                'main_unit_price_finance': unit_values['main_unit_price'],
                'main_unit_price_management': unit_values['main_unit_price'],
                'main_convert_rate': unit_values['main_convert_rate'],
                'main_quantity': unit_values['main_quantity'],
                'amount_finance_oc': amount,
                'amount_management_oc': amount,
                'description': move.name or inventory_item_name,
                'debit_account': debit_account,
                'credit_account': credit_account,
                'exchange_rate_operator': unit_values['exchange_rate_operator'],
                'account_object_name': account_object_name,
                'account_object_code': account_object_code,
                'inventory_item_code': inventory_item_code,
                'inventory_item_type': 0,
                'unit_name': unit_values['unit_name'],
                'stock_code': misa_warehouse_code,
                'main_unit_name': unit_values['main_unit_name'],
                'inventory_item_name': inventory_item_name,
                'stock_name': misa_warehouse_code,
                'account_name': debit_account,
                'is_follow_serial_number': False,
                'is_allow_duplicate_serial_number': False,
                'is_description': False,
                'is_description_import': False,
                'is_promotion_import': False,
                'un_resonable_cost_import': False,
                'pu_order_refid': pu_order_refid,
                'pu_order_ref_detail_id': pu_order_ref_detail_id,
                'pu_order_refno': purchase_order.name,
                'state': 0,
            })

        total_payment_amount = total_amount + total_vat_amount
        reference_items = self._prepare_misa_inward_references(
            purchase_order, refid, self.name, pu_order_refid
        )

        voucher = {
            'voucher_type': 18,
            # Keep the voucher/detail IDs we send. MISA can create different
            # internal IDs when this is true; reference UI still works through
            # org_refid, but purchase-order received qty depends on detail links.
            'is_get_new_id': False,
            'org_refid': refid,
            'is_allow_group': False,
            'org_refno': self.name,
            'org_reftype': 302,
            'org_reftype_name': 'Mua hang trong nuoc nhap kho chua thanh toan',
            'refid': refid,
            'act_voucher_type': 0,
            'reftype': 302,
            'reftype_name': 'Mua hang trong nuoc nhap kho chua thanh toan',
            'branch_id': branch_id,
            'account_object_id': account_object_id,
            'display_on_book': 0,
            'unit_price_method': 0,
            'reforder': int(datetime.utcnow().timestamp() * 1000),
            'refdate': self._to_misa_date(self.date_done),
            'posted_date': self._to_misa_date(self.date_done),
            'is_posted_finance': False,
            'is_posted_management': False,
            'is_posted_inventory_book_finance': False,
            'is_posted_inventory_book_management': False,
            'is_return_with_inward': False,
            'is_created_sa_return_last_year': False,
            'total_sale_amount': total_amount,
            'total_sale_amount_oc': total_amount,
            'total_vat_amount': total_vat_amount,
            'total_vat_amount_oc': total_vat_amount,
            'total_discount_amount': 0.0,
            'total_discount_amount_oc': 0.0,
            'total_inward_amount': total_amount,
            'total_inward_amount_oc': total_amount,
            'total_amount': total_payment_amount,
            'total_amount_oc': total_payment_amount,
            'total_amount_finance': total_payment_amount,
            'total_amount_management': total_payment_amount,
            'exchange_rate': 1.0,
            'refno_finance': '',
            'refno_management': '',
            'account_object_name': account_object_name,
            'account_object_address': partner.contact_address_complete or '',
            'journal_memo': 'Nhap kho tu don mua %s (Odoo: %s)' % (purchase_order.name, self.name),
            'currency_id': (purchase_order.currency_id.name or 'VND'),
            'account_object_code': account_object_code,
            'paid_status': 0,
            'is_paid': False,
            'is_executed': False,
            'is_adjust_value': False,
            'state': 0,
            'detail': detail,
        }
        return voucher, dictionary_items, reference_items

    def _prepare_misa_inward_references(self, purchase_order, inward_refid, inward_refno, purchase_order_refid):
        purchase_org_refid = (purchase_order.misa_purchase_order_org_refid or '').strip()
        refer_refid = purchase_org_refid or (purchase_order_refid or '').strip()
        if not refer_refid:
            return []
        return [{
            'org_refid': inward_refid,
            'org_refno': inward_refno,
            'org_reftype': 302,
            'org_reftype_name': 'Mua hang trong nuoc nhap kho chua thanh toan',
            'org_refer_refid': refer_refid,
            'org_refer_refno': purchase_order.name,
            'org_refer_reftype': 301,
            'org_refer_reftype_name': 'Don mua hang',
            'sort_order': 1,
        }]

    def _misa_move_ref_detail_id(self, move, prefix):
        ref_detail_id = str(uuid.uuid5(
            uuid.NAMESPACE_DNS,
            '%s|%d|%d' % (prefix, self.id, move.id)
        ))
        if (move.misa_ref_detail_id or '').strip() != ref_detail_id:
            move.sudo().write({'misa_ref_detail_id': ref_detail_id})
        return ref_detail_id

    def _misa_lookup_account_object_by_id(self, config, account_object_id):
        """Tìm item account_object trong MISA dictionary theo ID (UUID).
        Trả về dict item hoặc None. Dùng cached list (không call API thêm)."""
        if not account_object_id:
            return None
        uid_lower = account_object_id.lower()
        cache = self.env['amis.misa.vendor.cache'].sudo().search([
            ('config_id', '=', config.id),
            ('account_object_id', '=', uid_lower),
            ('is_deleted', '=', False),
            ('misa_inactive', '=', False),
        ], limit=1)
        if cache:
            return cache.to_misa_item()
        return None

    def _misa_lookup_account_object(self, config, partner):
        """Tìm account_object_id MISA theo tên partner, lưu vào partner."""
        if not partner:
            return ''
        cache, stale = self.env['amis.misa.vendor.cache'].sudo().lookup_for_partner(config, partner)
        if cache:
            misa_id = cache.account_object_id or ''
            if misa_id:
                partner.sudo().write({'misa_account_object_id': misa_id})
                if cache.partner_id.id != partner.id:
                    cache.sudo().write({'partner_id': partner.id})
                _logger.info('Auto-mapped partner %s → account_object_id=%s from MISA vendor cache', partner.name, misa_id)
            return misa_id
        if stale:
            _logger.warning('MISA vendor cache for partner %s is inactive/deleted: %s', partner.name, stale.account_object_id)
        else:
            _logger.warning('MISA vendor cache not found for partner: %s', partner.name)
        return ''

    def _misa_lookup_inventory_item(self, config, product, uom):
        existing_item_id = (product.misa_inventory_item_id or '').strip()
        existing_unit_id = (uom.misa_unit_id or '').strip() if uom else ''
        if existing_item_id:
            return existing_item_id, existing_unit_id

        code = (product.default_code or '').strip()
        if not code:
            return '', ''
        cache, stale = self.env['amis.misa.inventory.cache'].sudo().lookup_for_product(config, product)
        if cache:
            product.sudo().write({'misa_inventory_item_id': cache.inventory_item_id})
            if cache.product_id.id != product.id:
                cache.sudo().write({'product_id': product.id})
            cache_unit_name = (cache.unit_name or cache.main_unit_name or '').strip()
            if (
                cache.unit_id
                and uom
                and not (uom.misa_unit_id or '').strip()
                and cache_unit_name
                and (uom.name or '').strip().casefold() == cache_unit_name.casefold()
            ):
                uom.sudo().write({'misa_unit_id': cache.unit_id})
            _logger.info('Auto-mapped product %s from MISA inventory cache %s', code, cache.inventory_item_id)
            return cache.inventory_item_id, (uom.misa_unit_id or cache.unit_id or '')
        if stale:
            _logger.warning(
                'Skip MISA inventory cache for product %s: item %s is inactive/deleted.',
                code, stale.inventory_item_id,
            )
        else:
            _logger.warning('MISA inventory cache not found for product code: %s', code)
        return '', ''

    def _misa_lookup_unit(self, config, uom):
        """Tìm unit_id MISA theo tên uom, lưu vào uom."""
        if not uom:
            return ''
        name = (uom.name or '').strip()
        cache, stale = self.env['amis.misa.unit.cache'].sudo().lookup_for_uom(config, uom)
        if cache:
            unit_id = cache.unit_id or ''
            if unit_id:
                uom.sudo().write({'misa_unit_id': unit_id})
                _logger.info('Auto-mapped uom %s → unit_id=%s from MISA unit cache', name, unit_id)
            return unit_id
        if stale:
            _logger.warning('MISA unit cache for uom %s is inactive/deleted: %s', name, stale.unit_id)
        else:
            _logger.warning('MISA unit cache not found for uom: %s', name)
        return ''


class ResPartnerAmisMapping(models.Model):
    _inherit = 'res.partner'

    misa_account_object_id = fields.Char(
        string='MISA Account Object ID',
        help='ID thật của đối tượng (nhà cung cấp/khách hàng) trên MISA.',
    )


class ProductProductAmisMapping(models.Model):
    _inherit = 'product.product'

    misa_inventory_item_id = fields.Char(
        string='MISA Inventory Item ID',
        help='ID thật của vật tư/hàng hóa trên MISA.',
    )


class UomUomAmisMapping(models.Model):
    _inherit = 'uom.uom'

    misa_unit_id = fields.Char(
        string='MISA Unit ID',
        help='ID thật của đơn vị tính trên MISA.',
    )


class StockMoveAmisMapping(models.Model):
    _inherit = 'stock.move'

    misa_ref_detail_id = fields.Char(
        string='MISA Ref Detail ID',
        copy=False,
        help='ID thật của dòng chi tiết chứng từ trên MISA.',
    )
