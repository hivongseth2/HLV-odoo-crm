from odoo import models, api
from markupsafe import Markup
import re

_SKIP_MSG_RE = re.compile(
    r'Lệnh chuyển hàng được tạo'
    r'|lệnh chuyển hàng đã được tạo ra từ'
    r'|Đồng bộ \(xoá .{0,5} tạo lại\) thành công'
    r'|This transfer has been created from'
    r'|Transfer created'
    r'|Sales Order created'
    r'|Quotation created'
    r'|has been created from'
    r'|Đơn hàng được tạo',
    re.IGNORECASE
)


class DeliveryPlannerService(models.AbstractModel):
    _name = 'hlv.delivery.planner.service'
    _description = 'Delivery Planner Dashboard Service'

    @api.model
    def get_dashboard_data(
        self,
        search_query='', filter_warehouse_id='all',
        filter_delivery_status='all', filter_stock_status='all',
        filter_packing_status='all', filter_date_from='', filter_date_to='',
        filter_po_date_from='', filter_po_date_to='', filter_po_status='all',
        filter_done_date_from='', filter_done_date_to='',
        limit=12, offset=0, filter_saler_code='',
        filter_htgh='', filter_delivery_type='all', filter_tag_ids='',
        show_completed=False, filter_need_transfer=False,        filter_new_orders=False,    ):

        domain = self._build_search_domain(
            search_query, filter_warehouse_id,
            filter_delivery_status, filter_date_from, filter_date_to,
            filter_saler_code=filter_saler_code,
            filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
        )
        sales = self.env['sale.order'].search(
            domain,
            order='x_studio_misa_order_date desc nulls last, create_date desc, commitment_date asc, date_order desc'
        )

        sales, matched_ids, dashboard_stats, product_availabilities, so_status_dict = \
            self._calculate_po_and_stock_status(
                sales, filter_po_date_from, filter_po_date_to,
                filter_po_status, filter_delivery_status, filter_stock_status, filter_packing_status,
                show_completed=show_completed,
                filter_need_transfer=filter_need_transfer,
                filter_new_orders=filter_new_orders,
                filter_done_date_from=filter_done_date_from,
                filter_done_date_to=filter_done_date_to,
            )

        total_count = len(matched_ids)
        page_sales = self.env['sale.order'].browse(
            matched_ids[int(offset): int(offset) + int(limit)]
        )

        po_by_origin = self._fetch_pos_for_sales(page_sales)
        att_by_picking = self._fetch_attachments_for_pickings(page_sales.mapped('picking_ids').ids)
        so_packages_dict = self._fetch_packages_for_sales(page_sales)

        result = [
            self._format_dashboard_order(
                so, po_by_origin, product_availabilities,
                att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
            )
            for so in page_sales
        ]
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
        tags = self.env['crm.tag'].search_read([], ['id', 'name'])

        return {
            'orders': result,
            'warehouses': warehouses,
            'tags': tags,
            'total_count': total_count,
            'dashboard_stats': dashboard_stats,
        }

    @api.model
    def get_order_messages(self, order_id):
        so = self.env['sale.order'].browse(int(order_id))
        if not so.exists():
            return []
        picking_ids = so.picking_ids.ids
        domain = [
            '|',
            '&', ('model', '=', 'sale.order'), ('res_id', '=', so.id),
            '&', ('model', '=', 'stock.picking'), ('res_id', 'in', picking_ids),
        ]
        messages = self.env['mail.message'].search(domain, order='date desc', limit=200)
        picking_name_map = {p.id: p.name for p in so.picking_ids}
        result = []
        for msg in messages:
            plain = re.sub(r'<[^>]+>', '', msg.body or '').strip()
            has_att = bool(msg.attachment_ids)
            if not plain and not has_att:
                continue
            if plain and _SKIP_MSG_RE.search(plain):
                continue
            attachments = [{
                'id': att.id, 'name': att.name or '',
                'mimetype': att.mimetype or 'application/octet-stream',
                'file_size': att.file_size or 0,
            } for att in msg.attachment_ids]
            origin = ''
            if msg.model == 'stock.picking':
                origin = picking_name_map.get(msg.res_id, '')
            result.append({
                'id': msg.id,
                'date': msg.date.strftime('%d/%m/%Y %H:%M') if msg.date else '',
                'author': msg.author_id.name if msg.author_id else (msg.email_from or ''),
                'body': msg.body or '',
                'origin': origin,
                'attachments': attachments,
            })
        return result

    @api.model
    def post_order_message(self, order_id, body):
        so = self.env['sale.order'].browse(int(order_id))
        if not so.exists():
            return False
        safe_body = Markup('<p>%s</p>') % Markup.escape(body)
        so.message_post(
            body=safe_body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        return True


