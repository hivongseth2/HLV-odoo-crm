# -*- coding: utf-8 -*-
"""
Delivery Planner — AI Suggestion Helper
========================================
Backend service cho floating chat AI Dispatcher trong Delivery Planner.

KHÔNG đụng tới logic / file gốc của module — chỉ thêm 1 model mới.

Trách nhiệm:
1. Quản lý cấu hình chat (assistant mặc định, target sẵn vào "Knowledge Bot"
   hoặc bất kỳ assistant nào user chọn) qua ``ir.config_parameter``.
2. Khởi tạo / lấy thread của user hiện tại đã gắn assistant đó.
3. Gom dữ liệu bối cảnh + render prompt từ template Markdown trong
   ``data/skills/`` để dễ maintain.
"""
import logging
import os
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Khoá ir.config_parameter
_PARAM_ASSISTANT_ID = 'hlv_dp.chat.assistant_id'
_DEFAULT_ASSISTANT_NAME = 'Knowledge Bot'

# Đường dẫn tới folder skills (tương đối với file này)
_SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'skills',
)


def _read_skill_template(filename):
    """Đọc nội dung markdown skill từ disk. Cache bộ nhớ đơn giản."""
    path = os.path.join(_SKILLS_DIR, filename)
    if not os.path.exists(path):
        raise UserError(
            f"Không tìm thấy template skill: {filename}. Path: {path}"
        )
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class HlvDeliverySuggestion(models.AbstractModel):
    _name = 'hlv.delivery.suggestion'
    _description = 'HLV Delivery Planner — AI Suggestion Backend'

    # ──────────────────────────────────────────────────────────────────
    # CHAT SETUP — config & thread bootstrap
    # ──────────────────────────────────────────────────────────────────
    @api.model
    def _get_default_assistant(self):
        """Tìm assistant mặc định: ưu tiên config_parameter → Knowledge Bot
        → assistant đầu tiên public/active."""
        ICP = self.env['ir.config_parameter'].sudo()
        assistant_id = int(ICP.get_param(_PARAM_ASSISTANT_ID, '0') or 0)
        Assistant = self.env['llm.assistant'].sudo()

        if assistant_id:
            rec = Assistant.browse(assistant_id).exists()
            if rec and rec.active:
                return rec
        # fallback theo tên
        rec = Assistant.search(
            [('name', '=', _DEFAULT_ASSISTANT_NAME), ('active', '=', True)],
            limit=1,
        )
        if rec:
            return rec
        # fallback: assistant đầu tiên có model_id (có thể chạy được)
        return Assistant.search(
            [('active', '=', True), ('model_id', '!=', False)],
            limit=1,
            order='is_default desc, id asc',
        )

    @api.model
    def get_chat_setup(self):
        """Trả về cấu hình hiện tại + danh sách assistant cho UI picker."""
        Assistant = self.env['llm.assistant'].sudo()
        assistants = Assistant.search(
            [('active', '=', True)], order='is_default desc, name asc'
        )
        current = self._get_default_assistant()
        return {
            'current_assistant_id': current.id if current else False,
            'current_assistant_name': current.name if current else '',
            'current_model_name': current.model_id.name if (current and current.model_id) else '',
            'current_provider_name': current.provider_id.name if (current and current.provider_id) else '',
            'assistants': [
                {
                    'id': a.id,
                    'name': a.name,
                    'provider': a.provider_id.name or '',
                    'model': a.model_id.name or '',
                    'is_default': a.is_default,
                }
                for a in assistants
            ],
        }

    @api.model
    def set_chat_assistant(self, assistant_id):
        """Lưu assistant mặc định vào ir.config_parameter (sudo)."""
        if not assistant_id:
            raise UserError("Thiếu assistant_id.")
        rec = self.env['llm.assistant'].sudo().browse(int(assistant_id)).exists()
        if not rec:
            raise UserError("Assistant không tồn tại hoặc đã bị xoá.")
        self.env['ir.config_parameter'].sudo().set_param(
            _PARAM_ASSISTANT_ID, str(rec.id),
        )
        return self.get_chat_setup()

    @api.model
    def ensure_chat_thread(self, force_new=False):
        """Lấy thread chat AI Dispatcher cho user hiện tại.

        - Nếu ``force_new`` = True → tạo thread mới.
        - Ngược lại: lấy thread mới nhất do user tạo có gắn assistant này;
          nếu không có thì tạo mới.
        Trả về dict ``{thread_id, thread_name, assistant_id, assistant_name}``.
        """
        assistant = self._get_default_assistant()
        if not assistant:
            raise UserError(
                "Chưa có AI Assistant nào được cấu hình. "
                "Vui lòng vào menu LLM → Trợ lý để tạo Knowledge Bot."
            )
        if not assistant.model_id:
            raise UserError(
                f"Assistant '{assistant.name}' chưa có model. Vui lòng cấu hình."
            )

        Thread = self.env['llm.thread']
        thread = Thread

        if not force_new:
            thread = Thread.search([
                ('user_id', '=', self.env.uid),
                ('assistant_id', '=', assistant.id),
            ], limit=1, order='write_date desc')

        if not thread:
            vals = {
                'name': f"AI Dispatcher — {fields.Datetime.now().strftime('%Y-%m-%d %H:%M')}",
                'assistant_id': assistant.id,
            }
            if assistant.provider_id:
                vals['provider_id'] = assistant.provider_id.id
            if assistant.model_id:
                vals['model_id'] = assistant.model_id.id
            if assistant.prompt_id:
                vals['prompt_id'] = assistant.prompt_id.id
            thread = Thread.create(vals)
            # Đảm bảo tools / config sync như khi đổi assistant qua UI
            try:
                thread.set_assistant(assistant.id)
            except Exception:
                _logger.debug("set_assistant failed (non-fatal)", exc_info=True)

        # Strip native-only tools (vd: web_search của OpenAI) khi provider
        # không phải OpenAI — tránh lỗi "Không tìm thấy phương thức thực thi
        # web_search_execute" khi Anthropic/Claude tự gọi như function.
        try:
            self._sanitize_thread_tools(thread)
        except Exception:
            _logger.warning("Sanitize thread tools failed", exc_info=True)

        # Gắn 6 tool data-only của Delivery Planner vào thread (idempotent).
        try:
            self._attach_delivery_planner_tools(thread)
        except Exception:
            _logger.warning("Attach delivery planner tools failed", exc_info=True)

        return {
            'thread_id': thread.id,
            'thread_name': thread.name,
            'assistant_id': assistant.id,
            'assistant_name': assistant.name,
            'model_name': assistant.model_id.name or '',
            'provider_name': assistant.provider_id.name or '',
        }

    # ──────────────────────────────────────────────────────────────────
    # Internal: sanitize tools to avoid provider mismatches
    # ──────────────────────────────────────────────────────────────────
    # Các implementation chỉ chạy native trên provider OpenAI (không có
    # method *_execute trong Python). Nếu giữ lại trong thread khi provider
    # là Anthropic/khác, model sẽ tự xem như function tool và gọi
    # `<impl>_execute` → llm_tool raise "Không tìm thấy phương thức thực thi".
    _NATIVE_OPENAI_ONLY_IMPLS = {'web_search'}

    # Tên các tool LLM (decorator_method) thuộc Delivery Planner — auto
    # attach vào thread khi user mở floating chat. Khớp với
    # ``llm_tools_delivery.py``.
    _DP_TOOL_METHODS = (
        'tool_active_filter',
        'tool_dashboard_summary',
        'tool_list_orders',
        'tool_order_detail',
        'tool_list_routes',
        'tool_shipper_history',
    )

    def _attach_delivery_planner_tools(self, thread):
        """Đảm bảo thread có đủ 6 tool data-only của Delivery Planner."""
        Tool = self.env['llm.tool'].sudo()
        tools = Tool.search([
            ('decorator_model', '=', 'hlv.delivery.planner.tools'),
            ('decorator_method', 'in', list(self._DP_TOOL_METHODS)),
            ('active', '=', True),
        ])
        if not tools:
            _logger.warning(
                "No Delivery Planner LLM tools found — chạy lại với "
                "-u hlv_sale_delivery_planning để decorator @llm_tool "
                "đăng ký tool vào DB.",
            )
            return
        existing = set(thread.tool_ids.ids)
        to_add = [t.id for t in tools if t.id not in existing]
        if to_add:
            thread.write({'tool_ids': [(4, tid) for tid in to_add]})
            _logger.info(
                "Attached %d Delivery Planner tool(s) to thread %s: %s",
                len(to_add), thread.id,
                Tool.browse(to_add).mapped('name'),
            )

    def _sanitize_thread_tools(self, thread):
        """Bỏ các tool native-only khỏi thread khi provider không tương thích."""
        if not thread or not thread.tool_ids:
            return
        provider_service = (
            thread.provider_id and thread.provider_id.service or ''
        ).lower()
        if provider_service == 'openai':
            return  # OpenAI hỗ trợ native, giữ nguyên
        bad = thread.tool_ids.filtered(
            lambda t: (t.implementation or '') in self._NATIVE_OPENAI_ONLY_IMPLS
        )
        if bad:
            thread.write({'tool_ids': [(3, t.id) for t in bad]})
            _logger.info(
                "Stripped %d native-only tool(s) from thread %s (provider=%s): %s",
                len(bad), thread.id, provider_service, bad.mapped('name'),
            )

    # ──────────────────────────────────────────────────────────────────
    # SKILL 2 — Gợi ý giao hàng
    # ──────────────────────────────────────────────────────────────────
    @api.model
    def build_delivery_suggestion_prompt(self, sale_order_ids=None,
                                         warehouse_id=None,
                                         dashboard_filters=None,
                                         history_days=30, max_orders=60):
        """Đọc template Markdown + gom data context → trả về prompt string."""
        ctx = self._collect_delivery_context(
            sale_order_ids=sale_order_ids,
            warehouse_id=warehouse_id,
            dashboard_filters=dashboard_filters,
            history_days=history_days,
            max_orders=max_orders,
        )
        template = _read_skill_template('delivery_suggestion.md')
        try:
            return template.format(**ctx)
        except KeyError as e:
            _logger.warning("Skill template missing key %s — using safe fallback", e)
            # safe fallback: chỉ thay biến tồn tại
            return template

    @api.model
    def build_purchase_suggestion_prompt(self):
        """Placeholder skill 1."""
        template = _read_skill_template('purchase_suggestion.md')
        return template.format(placeholder_data='(chưa có dữ liệu — đang phát triển)')

    # ──────────────────────────────────────────────────────────────────
    # SKILL submit — post prompt vào thread (không qua URL/SSE)
    # ──────────────────────────────────────────────────────────────────
    @api.model
    def submit_skill_prompt(self, skill, thread_id=None, dashboard_filters=None,
                            **kwargs):
        """Render prompt + post thẳng vào thread như user message.

        ``dashboard_filters``: dict kiểu kwargs của ``get_dashboard_data``
        (filter_warehouse_id, filter_tag_ids, filter_htgh, search_query...).
        Nếu có → AI chỉ phân tích đúng đơn user đang xem trên Kanban.
        Mục đích: tránh nhét prompt (vài chục KB) vào querystring của
        EventSource (gây 414 Request-URI Too Large → "Lost connection").
        Frontend chỉ cần gọi ``startLLMStreaming(thread_id)`` (không kèm
        message) sau khi method này trả về.
        """
        df = dashboard_filters or {}
        # Lưu filter snapshot cho các tool LLM (dp_active_filter,
        # dp_list_orders... đọc từ ir.config_parameter theo uid).
        if df:
            try:
                self.env['hlv.delivery.planner.tools'].set_user_dashboard_context(df)
            except Exception:
                _logger.debug("set_user_dashboard_context failed", exc_info=True)
        if skill == 'delivery':
            prompt = self.build_delivery_suggestion_prompt(dashboard_filters=df)
        elif skill == 'purchase':
            prompt = self.build_purchase_suggestion_prompt()
        else:
            raise UserError(f"Skill không hợp lệ: {skill}")

        # Đảm bảo có thread của user hiện tại
        if not thread_id:
            info = self.ensure_chat_thread()
            thread_id = info['thread_id']
        thread = self.env['llm.thread'].browse(int(thread_id))
        if not thread.exists():
            raise UserError("Thread không tồn tại.")

        thread.message_post(
            body=prompt,
            llm_role='user',
            author_id=self.env.user.partner_id.id,
        )
        return {'thread_id': thread.id, 'prompt_length': len(prompt)}

    @api.model
    def archive_chat_thread(self, thread_id):
        """“Xóa” (= archive) thread chat — gọi khi user đóng panel hoặc bấm
        nhụt New. Thread cũ vẫn truy vết được qua menu LLM → Threads.
        Trả về True nếu OK, False nếu thread không tồn tại / không của user.
        """
        if not thread_id:
            return False
        Thread = self.env['llm.thread']
        thread = Thread.search([
            ('id', '=', int(thread_id)),
            ('user_id', '=', self.env.uid),
        ], limit=1)
        if not thread:
            return False
        try:
            thread.write({'active': False})
        except Exception:
            _logger.exception("archive_chat_thread failed for %s", thread_id)
            return False
        return True

    # ──────────────────────────────────────────────────────────────────
    # Internal: gather delivery context
    # ──────────────────────────────────────────────────────────────────
    def _collect_delivery_context(self, sale_order_ids=None, warehouse_id=None,
                                  dashboard_filters=None,
                                  history_days=30, max_orders=60):
        """Gom dữ liệu cho cột "ĐÃ ĐÓNG, CHỜ NHẬN GIAO".

        Dùng lại service ``hlv.delivery.planner.service.get_dashboard_data``
        với ``filter_packing_status='packed_waiting_ship'`` để KHỚP CHÍNH XÁC
        với danh sách đơn user đang thấy trên Kanban.

        Khi ``dashboard_filters`` (snoop từ FE) có đủ các filter hợp lệ
        (kho, tag, htgh, saler...) → mở rộng ``kwargs`` truyền thẳng cho
        get_dashboard_data → AI chỉ phân tích đúng đơn user đang xem.
        """
        Service = self.env['hlv.delivery.planner.service']
        kwargs = {
            'filter_packing_status': 'packed_waiting_ship',
            'limit': max_orders,
            'offset': 0,
            'include_stats': False,
        }
        # Merge filter từ dashboard (snoop FE) — chỉ wl các key hợp lệ,
        # không đặt khì giá trị rỗng / mặc định để bảo toàn default.
        _PASSTHROUGH = {
            'search_query', 'filter_warehouse_id',
            'filter_delivery_status', 'filter_stock_status',
            'filter_date_from', 'filter_date_to',
            'filter_done_date_from', 'filter_done_date_to',
            'filter_po_date_from', 'filter_po_date_to',
            'filter_po_status',
            'filter_saler_code', 'filter_htgh',
            'filter_delivery_type', 'filter_tag_ids',
            'show_completed', 'filter_need_transfer',
            'filter_new_orders', 'filter_print_status',
            'filter_shipper_received',
        }
        df = dashboard_filters or {}
        for k in _PASSTHROUGH:
            if k in df and df[k] not in (None, '', 'all'):
                kwargs[k] = df[k]
        # filter_packing_status: giữ “packed_waiting_ship” trừ khi user
        # chủ động chọn cột khác có nghiĩa → vẫn cho ưu tiên dashboard.
        if df.get('filter_packing_status') and df['filter_packing_status'] != 'all':
            kwargs['filter_packing_status'] = df['filter_packing_status']

        if warehouse_id and not df.get('filter_warehouse_id'):
            kwargs['filter_warehouse_id'] = warehouse_id
        if sale_order_ids:
            kwargs['domain'] = [('id', 'in', list(sale_order_ids))]

        try:
            dashboard = Service.get_dashboard_data(**kwargs)
        except Exception:
            _logger.exception("get_dashboard_data failed in suggestion")
            dashboard = {'orders': [], 'total_count': 0}

        raw_orders = dashboard.get('orders') or []
        order_ids = [o['id'] for o in raw_orders if o.get('id')]
        sale_orders = self.env['sale.order'].browse(order_ids)
        so_by_id = {so.id: so for so in sale_orders}

        orders_payload = []
        route_counter = defaultdict(int)
        route_value = defaultdict(float)

        for o in raw_orders:
            so = so_by_id.get(o['id'])
            if not so:
                continue
            partner = so.partner_shipping_id or so.partner_id

            # Tuyến = tag_ids (đã có trong payload)
            tag_pairs = o.get('tag_ids') or []
            route_tags = [t[1] for t in tag_pairs if isinstance(t, (list, tuple)) and len(t) > 1]
            route_label = ' / '.join(route_tags) if route_tags else (
                (partner.city or '') if partner else ''
            )

            # Địa chỉ: ưu tiên misa_shipping_address (đã có trong payload)
            address = o.get('misa_shipping_address') or ''
            if not address and partner:
                parts = [
                    partner.street, partner.street2, partner.city,
                    partner.state_id.name if partner.state_id else None,
                    partner.country_id.name if partner.country_id else None,
                ]
                address = ', '.join([p for p in parts if p])

            htgh = (o.get('x_studio_htgh') or '').strip()
            commitment = o.get('commitment_date') or ''
            scheduled_date = ''

            # Pickings flat từ payload (đã chứa shipper)
            pks = o.get('pickings') or []
            shipper_name = ''
            picking_names = []
            scheduled_candidates = []
            for p in pks:
                picking_names.append(p.get('name') or '')
                if p.get('shipper_user_id'):
                    su = p['shipper_user_id']
                    if isinstance(su, (list, tuple)) and len(su) > 1:
                        shipper_name = shipper_name or su[1]
                if p.get('scheduled_date'):
                    scheduled_candidates.append(p['scheduled_date'])
            if scheduled_candidates:
                scheduled_date = min(scheduled_candidates)

            # Sản phẩm: lấy pending từ order lines của SO (live)
            products = []
            for ml in so.order_line:
                if ml.product_id.type == 'service':
                    continue
                pending = (ml.product_uom_qty or 0) - (ml.qty_delivered or 0)
                if pending <= 0:
                    continue
                products.append({
                    'name': ml.product_id.display_name,
                    'qty': pending,
                    'uom': ml.product_uom.name if ml.product_uom else '',
                })

            wh_name = ''
            wh = o.get('warehouse_id')
            if isinstance(wh, (list, tuple)) and len(wh) > 1:
                wh_name = wh[1]

            orders_payload.append({
                'id': o['id'],
                'name': o.get('name') or so.name,
                'partner_name': partner.display_name if partner else '',
                'partner_phone': (partner.phone or partner.mobile or '') if partner else '',
                'address': address,
                'route': route_label,
                'tags': route_tags,
                'htgh': htgh,
                'amount_total': o.get('amount_total') or 0.0,
                'currency': so.currency_id.name if so.currency_id else 'VND',
                'commitment_date': commitment,
                'scheduled_date': scheduled_date,
                'warehouse': wh_name,
                'shipper_name': shipper_name,
                'product_count': len(products),
                'products': products[:25],
                'picking_names': [n for n in picking_names if n],
            })

            if route_label:
                route_counter[route_label] += 1
                route_value[route_label] += o.get('amount_total') or 0.0

        # Lịch sử shipper 30 ngày gần nhất (giữ logic cũ)
        Picking = self.env['stock.picking']
        date_from = fields.Datetime.now() - timedelta(days=history_days)
        hist_pickings = Picking.search([
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('date_done', '>=', date_from),
            ('shipper_user_id', '!=', False),
        ], limit=2000)

        shipper_history = {}
        for p in hist_pickings:
            su = p.shipper_user_id
            if not su:
                continue
            entry = shipper_history.setdefault(su.id, {
                'name': su.name,
                'completed_orders': 0,
                '_total_hours': 0.0,
                '_count_with_duration': 0,
                'avg_delivery_hours': None,
                'routes': defaultdict(int),
                'late_count': 0,
                'on_time_count': 0,
            })
            entry['completed_orders'] += 1

            # Thời gian giao thực tế
            start = None
            for fld in ('shipper_received_date', 'shipper_received_at',
                        'date_pack', 'scheduled_date'):
                if fld in p._fields:
                    val = getattr(p, fld, None)
                    if val:
                        start = val
                        break
            if start and p.date_done:
                try:
                    hours = (p.date_done - start).total_seconds() / 3600.0
                    if 0 < hours < 240:
                        entry['_total_hours'] += hours
                        entry['_count_with_duration'] += 1
                except Exception:
                    pass

            try:
                if p.scheduled_date and p.date_done:
                    if p.date_done > p.scheduled_date:
                        entry['late_count'] += 1
                    else:
                        entry['on_time_count'] += 1
            except Exception:
                pass

            try:
                so = p.sale_id
                if so:
                    for t in so.tag_ids:
                        entry['routes'][t.name] += 1
            except Exception:
                pass

        for v in shipper_history.values():
            if v['_count_with_duration']:
                v['avg_delivery_hours'] = round(
                    v['_total_hours'] / v['_count_with_duration'], 2,
                )
            v['routes'] = dict(sorted(
                v['routes'].items(), key=lambda kv: kv[1], reverse=True
            )[:8])
            v.pop('_total_hours', None)
            v.pop('_count_with_duration', None)

        # Render brief strings (template chỉ cần str)
        return {
            'generated_at': fields.Datetime.now().isoformat(),
            'history_days': history_days,
            'total_orders': len(orders_payload),
            'filter_brief': self._render_filter_brief(df),
            'orders_brief': self._render_orders_brief(orders_payload),
            'routes_brief': self._render_routes_brief(route_counter, route_value),
            'history_brief': self._render_history_brief(shipper_history, history_days),
        }

    def _render_filter_brief(self, df):
        """Mô tả filter user đang dùng để AI biết scope."""
        if not df:
            return '_(không có filter — toàn hệ thống, packed_waiting_ship)_'
        bits = []
        wh_id = df.get('filter_warehouse_id')
        if wh_id and wh_id != 'all':
            try:
                wh = self.env['stock.warehouse'].browse(int(wh_id))
                if wh.exists():
                    bits.append(f"Kho = **{wh.name}**")
            except Exception:
                pass
        tag_ids = df.get('filter_tag_ids')
        if tag_ids:
            try:
                ids = [int(x) for x in str(tag_ids).split(',') if str(x).strip()]
                tags = self.env['crm.tag'].browse(ids)
                names = [t.name for t in tags if t.exists()]
                if names:
                    bits.append(f"Tag = **{', '.join(names)}**")
            except Exception:
                pass
        for k, label in [
            ('filter_htgh', 'HTGH'),
            ('filter_saler_code', 'Mã saler'),
            ('filter_delivery_type', 'Loại VC'),
            ('filter_delivery_status', 'Trạng thái giao'),
            ('filter_stock_status', 'Trạng thái kho'),
            ('filter_packing_status', 'Trạng thái đóng gói'),
            ('filter_print_status', 'Trạng thái in'),
            ('filter_shipper_received', 'Shipper nhận'),
            ('search_query', 'Tìm kiếm'),
            ('filter_date_from', 'Từ ngày'),
            ('filter_date_to', 'Đến ngày'),
        ]:
            v = df.get(k)
            if v and v != 'all':
                bits.append(f"{label} = **{v}**")
        return ' | '.join(bits) if bits else '_(không có filter — toàn hệ thống)_'

    def _render_orders_brief(self, orders):
        if not orders:
            return '_(không có đơn nào ở trạng thái ĐÃ ĐÓNG, CHỜ NHẬN GIAO)_'
        lines = []
        for i, o in enumerate(orders, 1):
            products = '; '.join(
                f"{p['name']} x{p['qty']}{(' ' + p['uom']) if p['uom'] else ''}"
                for p in o['products']
            )
            try:
                amount_str = f"{int(o['amount_total'] or 0):,}".replace(',', '.')
            except Exception:
                amount_str = str(o['amount_total'])
            lines.append(
                f"{i}. **[{o['name']}]** {o['partner_name']}\n"
                f"   - Địa chỉ: {o['address'] or '_(thiếu)_'}\n"
                f"   - Tuyến/Tag: {o['route'] or '_(chưa phân)_'} | HTGH: {o['htgh'] or '_(chưa)_'}\n"
                f"   - Hẹn giao: {o['commitment_date'] or o['scheduled_date'] or '_(chưa)_'} | Kho: {o['warehouse']}\n"
                f"   - Giá trị: {amount_str} {o['currency']}\n"
                f"   - Shipper hiện tại: {o['shipper_name'] or '_(chưa gán)_'}\n"
                f"   - Sản phẩm ({o['product_count']}): {products or '_(không có)_'}\n"
                f"   - Phiếu: {', '.join(o['picking_names'])}"
            )
        return '\n\n'.join(lines)

    def _render_routes_brief(self, route_counter, route_value):
        if not route_counter:
            return '_(không có dữ liệu tuyến)_'
        rows = sorted(route_counter.items(), key=lambda kv: kv[1], reverse=True)
        lines = []
        for r, cnt in rows:
            try:
                val_str = f"{int(route_value[r] or 0):,}".replace(',', '.')
            except Exception:
                val_str = str(route_value[r])
            lines.append(f"- **{r}**: {cnt} đơn, tổng {val_str}đ")
        return '\n'.join(lines)

    def _render_history_brief(self, shipper_history, history_days):
        if not shipper_history:
            return '_(chưa có lịch sử shipper)_'
        lines = []
        for h in shipper_history.values():
            on_time_total = h['on_time_count'] + h['late_count']
            on_time_rate = (
                round(100 * h['on_time_count'] / on_time_total)
                if on_time_total else None
            )
            route_top = ', '.join(f"{r}({c})" for r, c in h['routes'].items())
            lines.append(
                f"- **{h['name']}**: {h['completed_orders']} đơn/{history_days} ngày, "
                f"TB **{h['avg_delivery_hours'] or '?'}h/phiếu**, "
                f"đúng giờ **{on_time_rate if on_time_rate is not None else '?'}%**, "
                f"tuyến quen: {route_top or '_(không)_'}"
            )
        return '\n'.join(lines)
