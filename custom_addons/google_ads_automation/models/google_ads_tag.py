from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging
import json

_logger = logging.getLogger(__name__)

try:
    import requests as _requests
except ImportError:
    _requests = None


class GoogleAdsTag(models.Model):
    _name = 'google.ads.tag'
    _description = 'Cấu Hình Google Tag / GTM'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    name = fields.Char(string='Tên Cấu Hình', required=True)
    account_id = fields.Many2one(
        'google.ads.account', string='Tài Khoản Google Ads',
        required=True, ondelete='cascade',
    )
    active = fields.Boolean(default=True)

    # ── Tag Type ──────────────────────────────────
    tag_type = fields.Selection([
        ('gtag',    'Google Tag (gtag.js) — Trực tiếp'),
        ('gtm',     'Google Tag Manager (GTM)'),
    ], string='Loại Tag', required=True, default='gtm',
        help='GTM dễ quản lý hơn, khuyến nghị dùng GTM')

    # ── Google Tag (gtag) ─────────────────────────
    measurement_id = fields.Char(
        string='Measurement ID / AW ID',
        help='Dạng G-XXXXXXXX (GA4) hoặc AW-XXXXXXXXX (Google Ads)',
    )

    # ── Google Tag Manager ────────────────────────
    gtm_container_id = fields.Char(
        string='GTM Container ID',
        help='Dạng GTM-XXXXXXX',
    )

    # ── Conversion Actions ───────────────────────
    conversion_action_ids = fields.One2many(
        'google.ads.conversion.action',
        'tag_id', string='Conversion Actions',
    )

    # ── Dữ liệu GTM đã đồng bộ ─────────────────
    gtm_item_ids = fields.One2many(
        'google.ads.gtm.item',
        'tag_config_id', string='Thành Phần GTM',
    )
    gtm_tag_count = fields.Integer(
        string='Số Tags', compute='_compute_gtm_counts',
    )
    gtm_trigger_count = fields.Integer(
        string='Số Triggers', compute='_compute_gtm_counts',
    )
    gtm_variable_count = fields.Integer(
        string='Số Biến', compute='_compute_gtm_counts',
    )

    # ── GTM API credentials (chỉ cần cho Real mode) ──
    gtm_auth_type = fields.Selection([
        ('oauth', 'OAuth 2.0 (Lấy chung từ cài đặt Tài Khoản Google)'),
        ('service_account', 'Service Account (File JSON)'),
    ], string='Kiểu Xác Thực', default='oauth')
    gtm_account_id = fields.Char(
        string='GTM Account ID',
        help='Lấy từ GTM > Admin > Account Settings (dạng số)',
    )
    gtm_access_token = fields.Char(
        string='Access Token (Thủ Công)',
        password=True,
        help='OAuth2 access token sống 1 tiếng. Nếu để trống, hệ thống sẽ tự sinh mã mới dựa trên Refresh Token của Tài khoản Google.',
    )
    
    # ── GA4 Kho dữ liệu ──
    ga4_property_id = fields.Char(
        string='GA4 Property ID',
        help='Dãy số ID của thuộc tính thẻ GA4 (Ví dụ: 312345678). Dùng để kéo Báo Cáo.',
    )
    
    # ── Dashboard Analytics ──
    ga4_dashboard_html = fields.Html(
        string='Báo cáo GA4', 
        compute='_compute_ga4_dashboard', 
        store=False, sanitize=False
    )

    @api.depends('gtm_item_ids', 'gtm_item_ids.item_type')
    def _compute_gtm_counts(self):
        for rec in self:
            items = rec.gtm_item_ids
            rec.gtm_tag_count = len(items.filtered(lambda i: i.item_type == 'tag'))
            rec.gtm_trigger_count = len(items.filtered(lambda i: i.item_type == 'trigger'))
            rec.gtm_variable_count = len(items.filtered(lambda i: i.item_type == 'variable'))

    def action_sync_from_gtm(self):
        """Kéo dữ liệu Tags/Triggers/Variables từ GTM API về Odoo (GET only)"""
        self.ensure_one()

        # Real mode (hoặc Demo mode nhưng có điền 1 trong 2 loại Token) → gọi GTM API v2
        is_real_sync = not (self.account_id and self.account_id.is_demo)
        has_manual_token = bool(self.gtm_access_token and self.gtm_account_id)
        has_auto_token = bool(self.account_id.refresh_token and self.account_id.client_id and self.account_id.client_secret and self.gtm_account_id)
        
        if self.account_id and self.account_id.is_demo and (has_manual_token or has_auto_token):
            is_real_sync = True # Force real sync if credentials are provided in demo mode

        if not is_real_sync:
            # Thuần Demo mode (chưa điền token) → seed fake data
            self._demo_seed_gtm_items()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('DEMO — Đồng Bộ GTM Hoàn Tất'),
                    'message': _('Đã tạo dữ liệu mẫu: Tags, Triggers, Variables.'),
                    'type': 'success',
                    'sticky': False,
                },
            }

        # Bắt đầu luồng Real API
        if not _requests:
            raise UserError(_('Thiếu thư viện "requests". Chạy: pip install requests'))
            
        if not self.gtm_account_id or not self.gtm_container_id:
            raise UserError(_('Vui lòng điền tối thiểu: GTM Account ID và Container ID.'))

        final_access_token = False

        if self.gtm_auth_type == 'service_account':
            if not self.account_id.service_account_json:
                raise UserError(_('Vui lòng dán nội dung file JSON của Service Account vào tab Tài Khoản Google.'))
            try:
                from google.oauth2 import service_account
                import google.auth.transport.requests
            except ImportError:
                raise UserError(_('Thiếu thư viện "google-auth". Vui lòng chạy lệnh: pip install google-auth'))
            
            try:
                import json
                sa_info = json.loads(self.account_id.service_account_json)
                credentials = service_account.Credentials.from_service_account_info(
                    sa_info,
                    scopes=['https://www.googleapis.com/auth/tagmanager.readonly', 'https://www.googleapis.com/auth/analytics.readonly']
                )
                request = google.auth.transport.requests.Request()
                credentials.refresh(request)
                final_access_token = credentials.token
                self.gtm_access_token = final_access_token
            except Exception as e:
                raise UserError(_('Lỗi xác thực Service Account: %s') % str(e))
                
        else:
            # OAuth2 Flow (Sử dụng chung cấu hình với Account Google Ads)
            if not self.gtm_access_token and not (self.account_id.refresh_token and self.account_id.client_id and self.account_id.client_secret):
                 raise UserError(_('Vui lòng điền [Access Token (Thủ Công)] HOẶC khai báo ĐỦ BỘ [Client ID + Secret + Refresh Token] bên tab Tài Khoản Google.'))

            final_access_token = self.gtm_access_token

            # Nếu cấu hình đủ bộ Refresh Token => Bỏ qua Access Token thủ công, ưu tiên lấy Token mới
            if self.account_id.refresh_token and self.account_id.client_id and self.account_id.client_secret:
                token_url = 'https://oauth2.googleapis.com/token'
                token_data = {
                    'client_id': self.account_id.client_id,
                    'client_secret': self.account_id.client_secret,
                    'refresh_token': self.account_id.refresh_token,
                    'grant_type': 'refresh_token',
                }
                try:
                    token_resp = _requests.post(token_url, data=token_data, timeout=10)
                    token_resp.raise_for_status()
                    final_access_token = token_resp.json().get('access_token')
                    if not final_access_token:
                        raise UserError(_('Không lấy được Access Token tự động từ Google. Hãy kiểm tra lại Refresh Token và Client ID/Secret ở tab Tài Khoản Google.'))
                    
                    # Cập nhật lại ô Access Token thủ công trên giao diện để user thấy
                    self.gtm_access_token = final_access_token
                except _requests.exceptions.RequestException as e:
                    err_msg = str(e)
                    if hasattr(e, 'response') and e.response is not None:
                        err_msg += f" - {e.response.text}"
                    raise UserError(_('Lỗi khi xin Access Token mới tự động từ Account: %s') % err_msg)

        if not final_access_token:
            raise UserError(_('Không có Access Token hợp lệ để gọi GTM API.'))

        container_num = self.gtm_container_id.replace('GTM-', '')
        base_url = (
            f'https://www.googleapis.com/tagmanager/v2'
            f'/accounts/{self.gtm_account_id}'
            f'/containers/{container_num}'
        )
        headers = {'Authorization': f'Bearer {final_access_token}'}

        # Lấy workspace mặc định
        try:
            ws_resp = _requests.get(f'{base_url}/workspaces', headers=headers, timeout=15)
            ws_resp.raise_for_status()
            workspaces = ws_resp.json().get('workspace', [])
            if not workspaces:
                raise UserError(_('Không tìm thấy Workspace nào trong GTM Container.'))
            ws_id = workspaces[0]['workspaceId']
        except _requests.exceptions.RequestException as e:
            raise UserError(_('Lỗi kết nối GTM API: %s') % str(e))

        ws_url = f'{base_url}/workspaces/{ws_id}'
        now = fields.Datetime.now()

        # Fetch Tags
        self._fetch_gtm_endpoint(ws_url, 'tags', 'tag', headers, now)
        # Fetch Triggers
        self._fetch_gtm_endpoint(ws_url, 'triggers', 'trigger', headers, now)
        # Fetch Variables
        self._fetch_gtm_endpoint(ws_url, 'variables', 'variable', headers, now)
        
        # ── Kéo Thêm Dữ liệu Thực Tế Từ GA4 Data API ──
        if self.ga4_property_id:
            try:
                self._fetch_ga4_event_counts(self.ga4_property_id, final_access_token)
            except Exception as e:
                _logger.error(f"Lỗi kéo báo cáo GA4: {e}", exc_info=True)
                from markupsafe import Markup
                err_msg = Markup('<div style="background-color: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px; border-radius: 4px; color: #92400e; font-size: 13px;"><b style="display: block; margin-bottom: 4px;">⚠️ Đồng bộ GTM thành công nhưng lỗi khi lấy báo cáo GA4</b><code style="font-family: Consolas, monospace; background-color: rgba(255, 255, 255, 0.5); padding: 2px 4px; border-radius: 3px;">%s</code></div>') % str(e)
                self.message_post(body=err_msg)

        self.message_post(body=_(
            'Đã đồng bộ từ GTM: %d Tags, %d Triggers, %d Biến'
        ) % (self.gtm_tag_count, self.gtm_trigger_count, self.gtm_variable_count))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đồng Bộ GTM & GA4 Hoàn Tất'),
                'message': _('%d Tags, %d Triggers, %d Biến') % (
                    self.gtm_tag_count, self.gtm_trigger_count, self.gtm_variable_count,
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def _fetch_ga4_event_counts(self, property_id, access_token):
        """Dùng Data API v1 runReport kéo số lượt kích hoạt (events) 30 ngày qua"""
        import requests
        from markupsafe import Markup
        import json
        
        _logger.info(f"Bắt đầu kéo báo cáo GA4 cho property_id={property_id}")
        url = f'https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport'
        headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
        payload = {
          "dateRanges": [{"startDate": "30daysAgo", "endDate": "today"}],
          "dimensions": [{"name": "eventName"}],
          "metrics": [{"name": "eventCount"}]
        }
        
        _logger.info(f"GA4 POST URL: {url}")
        _logger.info(f"GA4 Payload: {json.dumps(payload)}")
        
        # Tăng timeout lên 45s vì API Báo cáo của Google Analytics thi thoảng tổng hợp data khá chậm
        resp = requests.post(url, headers=headers, json=payload, timeout=45)
        
        _logger.info(f"GA4 Response Status: {resp.status_code}")
        _logger.info(f"GA4 Response Content: {resp.text}")
        
        # Ghi log tóm tắt vào chatter để User dễ debug
        log_html = f"""
            <div style="background-color: #f4f6f9; border-left: 4px solid #1f2937; padding: 12px 16px; border-radius: 4px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin: 8px 0;">
                <h4 style="margin: 0 0 8px 0; color: #1f2937; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">📋 Nhật ký kiểm tra GA4 API</h4>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <tr>
                        <td style="padding: 4px 0; color: #6b7280; width: 120px;"><b>Property ID:</b></td>
                        <td style="padding: 4px 0; color: #111827; font-family: monospace;">{property_id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 4px 0; color: #6b7280;"><b>Status Code:</b></td>
                        <td style="padding: 4px 0;">
                            <span style="display: inline-block; padding: 2px 6px; border-radius: 12px; font-size: 11px; font-weight: 600; {'background-color: #d1fae5; color: #065f46;' if str(resp.status_code).startswith('2') else 'background-color: #fee2e2; color: #991b1b;'}">
                                {resp.status_code}
                            </span>
                        </td>
                    </tr>
                </table>
                <div style="margin-top: 10px;">
                    <b style="color: #6b7280; font-size: 12px; text-transform: uppercase;">Raw Response:</b>
                    <pre style="background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; padding: 10px; font-family: 'Consolas', 'Monaco', monospace; font-size: 12px; color: #374151; max-height: 250px; overflow-y: auto; white-space: pre-wrap; word-wrap: break-word; margin-top: 4px;">{Markup.escape(resp.text)}</pre>
                </div>
            </div>
        """
        self.message_post(body=Markup(log_html))
        
        resp.raise_for_status()
        data = resp.json()
        
        rows = data.get('rows', [])
        # Tạo từ điển tên event -> số đếm
        event_dict = {}
        for row in rows:
            ev_name = row['dimensionValues'][0]['value']
            ev_count = int(row['metricValues'][0]['value'])
            event_dict[ev_name] = ev_count
            
        _logger.info(f"GA4 Parsed Events Map: {event_dict}")
            
        # Nạp số đếm vào các Tag GA4 Event đang có trong Odoo
        ga4_tags = self.gtm_item_ids.filtered(lambda t: t.item_type == 'tag' and t.tag_subtype == 'ga4_event')
        
        # Mảng debug tạm thời để in ra chatter
        debug_logs = []
        
        for tag in ga4_tags:
            # GTM Tag name có thể khác Event Name trong GA4.
            actual_event_name = tag.name
            if tag.notes:
                try:
                    params = json.loads(tag.notes)
                    for p in params:
                        # GTM API trả về format: {"type": "template", "key": "eventName", "value": "add_to_cart"}
                        # Có thể key là 'eventName', 'name', hoặc tùy trường hợp
                        if p.get('key') in ('eventName', 'name') and p.get('value'):
                            actual_event_name = p.get('value')
                            break
                        # Nếu parameter "eventParameters" chứa danh sách các param con, thử tìm
                        if p.get('key') == 'eventParameters' and getattr(p.get('list'), '__iter__', False):
                            for sub_p in p['list']:
                                if isinstance(sub_p, dict) and sub_p.get('type') == 'map':
                                    map_items = sub_p.get('map', [])
                                    # ... logic quét sâu hơn nếu bị giấu trong biến (ít xảy ra)
                except Exception:
                    pass
            
            match_count = event_dict.get(actual_event_name, 0)
            
            # ── HARDCODED MAPS: Xử lý râu ông nọ cắm cằm bà kia (Custom GTM config) ──
            # Nếu tên event trên GTM không giống với tên event chuẩn của Google Analytics
            if match_count == 0:
                hardcode_map = {
                    'Them_vao_gio': 'add_to_cart',
                    'GA4_Them_vao_gio_hang': 'add_to_cart', # Đề phòng người dùng set theo cả tên tag
                    'Mua_ngay': 'purchase', # Giả định Mua_ngay bắn event mua hàng
                    'Mua_tra_gop': 'purchase',
                    'GA4_Mua_ngay': 'purchase',
                    'GA4_Mua_tra_gop': 'purchase'
                }
                
                mapped_name = hardcode_map.get(actual_event_name) or hardcode_map.get(tag.name)
                if mapped_name:
                    match_count = event_dict.get(mapped_name, 0)
                    if match_count > 0:
                         actual_event_name = f"{actual_event_name} -> {mapped_name}"
            
            # Fallback cuối: thử tìm theo tên Tag (tag.name)
            if match_count == 0:
                match_count = event_dict.get(tag.name, 0)
            
            if match_count == 0:
                debug_logs.append(f"Tag: {tag.name} | Cố tìm event: {actual_event_name} | KHÔNG MATCH | Xem log server để thấy full JSON")
                _logger.warning(f"====== GA4 TAG MISMATCH: {tag.name} ======")
                _logger.warning(f"GTM NOTES JSON FULL:")
                _logger.warning(tag.notes)
                _logger.warning("===========================================")
            else:
                debug_logs.append(f"Tag: {tag.name} | MATCH THÀNH CÔNG event: {actual_event_name} | Số lượng: {match_count}")
                
            tag.ga4_event_count = match_count
            
        if debug_logs:
            debug_html = "<br/>".join(debug_logs)
            self.message_post(body=Markup(f'<div style="font-size: 11px; font-family: monospace; background: #eee; padding: 5px;"><b>(Debug) Kết quả map sự kiện:</b><br/>{Markup.escape(debug_html)}</div>'))


    def _fetch_gtm_endpoint(self, ws_url, endpoint, item_type, headers, now):
        """GET dữ liệu từ 1 endpoint GTM API và lưu vào Odoo"""
        GtmItem = self.env['google.ads.gtm.item']
        try:
            resp = _requests.get(f'{ws_url}/{endpoint}', headers=headers, timeout=15)
            resp.raise_for_status()
            items = resp.json().get(endpoint.rstrip('s'), resp.json().get(endpoint, []))
            if isinstance(items, dict):
                items = [items]
        except Exception as e:
            _logger.warning('GTM API %s error: %s', endpoint, e)
            return

        for item in items:
            gtm_id = item.get('tagId') or item.get('triggerId') or item.get('variableId', '')
            name = item.get('name', 'Không tên')
            existing = GtmItem.search([
                ('tag_config_id', '=', self.id),
                ('gtm_item_id', '=', str(gtm_id)),
                ('item_type', '=', item_type),
            ], limit=1)

            vals = {
                'tag_config_id': self.id,
                'gtm_item_id': str(gtm_id),
                'name': name,
                'item_type': item_type,
                'is_paused': item.get('paused', False),
                'notes': json.dumps(item.get('parameter', []), ensure_ascii=False, indent=2)[:2000] if item.get('parameter') else '',
                'last_synced': now,
            }

            # Map subtypes
            if item_type == 'tag':
                tag_type_map = {
                    'ua': 'ua', 'gaawc': 'ga4_config', 'gaawe': 'ga4_event',
                    'awct': 'awct', 'sp': 'aw_remarketing', 'html': 'html',
                }
                vals['tag_subtype'] = tag_type_map.get(item.get('type', ''), 'other')
                # Lấy trigger names
                trigger_refs = item.get('firingTriggerId', [])
                if trigger_refs:
                    triggers = GtmItem.search([
                        ('tag_config_id', '=', self.id),
                        ('item_type', '=', 'trigger'),
                        ('gtm_item_id', 'in', [str(t) for t in trigger_refs]),
                    ])
                    vals['firing_trigger_names'] = ', '.join(triggers.mapped('name')) if triggers else ''

            elif item_type == 'trigger':
                trigger_type_map = {
                    'pageview': 'pageview', 'click': 'click',
                    'formSubmission': 'form_submit', 'timer': 'timer',
                    'scrollDepth': 'scroll_depth', 'customEvent': 'custom_event',
                    'historyChange': 'history_change', 'domReady': 'dom_ready',
                    'windowLoaded': 'window_loaded',
                }
                vals['trigger_subtype'] = trigger_type_map.get(item.get('type', ''), 'other')

            if existing:
                existing.write(vals)
            else:
                GtmItem.create(vals)

    def _demo_seed_gtm_items(self):
        """Tạo dữ liệu GTM mẫu cho demo mode"""
        self.ensure_one()
        GtmItem = self.env['google.ads.gtm.item']
        now = fields.Datetime.now()

        demo_data = [
            # ── Tags ──
            {'gtm_item_id': 'T1', 'name': 'GA4 Config — Cấu Hình Chính',
             'item_type': 'tag', 'tag_subtype': 'ga4_config',
             'firing_trigger_names': 'All Pages', 'is_paused': False},
            {'gtm_item_id': 'T2', 'name': 'GA4 Event — Mua Hàng (Purchase)',
             'item_type': 'tag', 'tag_subtype': 'ga4_event',
             'firing_trigger_names': 'Purchase Success', 'is_paused': False},
            {'gtm_item_id': 'T3', 'name': 'Google Ads — Conversion Tracking',
             'item_type': 'tag', 'tag_subtype': 'awct',
             'firing_trigger_names': 'Purchase Success', 'is_paused': False},
            {'gtm_item_id': 'T4', 'name': 'Google Ads — Remarketing',
             'item_type': 'tag', 'tag_subtype': 'aw_remarketing',
             'firing_trigger_names': 'All Pages', 'is_paused': False},
            {'gtm_item_id': 'T5', 'name': 'Facebook Pixel',
             'item_type': 'tag', 'tag_subtype': 'html',
             'firing_trigger_names': 'All Pages', 'is_paused': False},
            {'gtm_item_id': 'T6', 'name': 'Hotjar Tracking Code',
             'item_type': 'tag', 'tag_subtype': 'html',
             'firing_trigger_names': 'All Pages', 'is_paused': True},

            # ── Triggers ──
            {'gtm_item_id': 'TR1', 'name': 'All Pages',
             'item_type': 'trigger', 'trigger_subtype': 'pageview'},
            {'gtm_item_id': 'TR2', 'name': 'Purchase Success',
             'item_type': 'trigger', 'trigger_subtype': 'custom_event',
             'notes': 'Event name: purchase'},
            {'gtm_item_id': 'TR3', 'name': 'Add To Cart Click',
             'item_type': 'trigger', 'trigger_subtype': 'click',
             'notes': 'CSS Selector: .add-to-cart-button'},
            {'gtm_item_id': 'TR4', 'name': 'Form Liên Hệ Submit',
             'item_type': 'trigger', 'trigger_subtype': 'form_submit',
             'notes': 'Form ID: contact-form'},
            {'gtm_item_id': 'TR5', 'name': 'Cuộn Trang 50%',
             'item_type': 'trigger', 'trigger_subtype': 'scroll_depth',
             'notes': 'Vertical: 50%'},
            {'gtm_item_id': 'TR6', 'name': 'DOM Ready',
             'item_type': 'trigger', 'trigger_subtype': 'dom_ready'},

            # ── Variables ──
            {'gtm_item_id': 'V1', 'name': 'GA4 Measurement ID',
             'item_type': 'variable', 'notes': 'G-XXXXXXXXXX'},
            {'gtm_item_id': 'V2', 'name': 'Google Ads Conversion ID',
             'item_type': 'variable', 'notes': 'AW-XXXXXXXXX'},
            {'gtm_item_id': 'V3', 'name': 'Transaction Value',
             'item_type': 'variable', 'notes': 'DataLayer: ecommerce.value'},
            {'gtm_item_id': 'V4', 'name': 'Transaction ID',
             'item_type': 'variable', 'notes': 'DataLayer: ecommerce.transaction_id'},
        ]

        for d in demo_data:
            existing = GtmItem.search([
                ('tag_config_id', '=', self.id),
                ('gtm_item_id', '=', d['gtm_item_id']),
            ], limit=1)
            vals = {
                'tag_config_id': self.id,
                'last_synced': now,
                **d,
            }
            if existing:
                existing.write(vals)
            else:
                GtmItem.create(vals)

    # ── Generated snippets (computed) ────────────
    snippet_head = fields.Text(
        string='Code Dán Vào <head>',
        compute='_compute_snippets', store=False,
    )
    snippet_body = fields.Text(
        string='Code Dán Sau <body>',
        compute='_compute_snippets', store=False,
    )
    snippet_purchase = fields.Text(
        string='Code Theo Dõi Đơn Hàng (WooCommerce)',
        compute='_compute_snippets', store=False,
    )

    @api.depends('tag_type', 'measurement_id', 'gtm_container_id', 'conversion_action_ids')
    def _compute_snippets(self):
        for tag in self:
            if tag.tag_type == 'gtm':
                tag.snippet_head, tag.snippet_body = tag._make_gtm_snippets()
                tag.snippet_purchase = tag._make_gtm_purchase_snippet()
            else:
                tag.snippet_head = tag._make_gtag_snippet()
                tag.snippet_body = ''
                tag.snippet_purchase = tag._make_gtag_purchase_snippet()

    def _make_gtm_snippets(self):
        container = self.gtm_container_id or 'GTM-XXXXXXX'
        head = f"""<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':
new Date().getTime(),event:'gtm.js'}});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
}})(window,document,'script','dataLayer','{container}');</script>
<!-- End Google Tag Manager -->"""

        body = f"""<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={container}"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->"""
        return head, body

    def _make_gtm_purchase_snippet(self):
        """Snippet PHP cho WooCommerce thankyou page (dán vào functions.php)"""
        actions = self.conversion_action_ids.filtered(
            lambda a: a.action_type == 'purchase'
        )
        if not actions:
            return '/* Chưa có Conversion Action loại Mua Hàng */'

        action = actions[0]
        return f"""<?php
// Dán vào functions.php của theme WordPress
// Theo dõi đơn hàng WooCommerce → Google Tag Manager DataLayer
add_action('woocommerce_thankyou', 'hlv_gtm_purchase_event', 10, 1);
function hlv_gtm_purchase_event($order_id) {{
    if (!$order_id) return;
    $order = wc_get_order($order_id);
    $items = array();
    foreach ($order->get_items() as $item) {{
        $items[] = array(
            'item_id'   => $item->get_product_id(),
            'item_name' => $item->get_name(),
            'quantity'  => $item->get_quantity(),
            'price'     => $item->get_total(),
        );
    }}
    ?>
    <script>
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({{
        'event': 'purchase',
        'ecommerce': {{
            'transaction_id': '<?php echo $order_id; ?>',
            'value': '<?php echo $order->get_total(); ?>',
            'currency': '<?php echo $order->get_currency(); ?>',
            'items': <?php echo json_encode($items); ?>
        }},
        /* Gclid để link với Google Ads */
        'gclid': '<?php echo $order->get_meta("_ga_gclid", true); ?>'
    }});
    </script>
    <?php
}}
/* Conversion Label: {action.conversion_label} */
/* Conversion ID: {action.conversion_id} */"""

    def _make_gtag_snippet(self):
        mid = self.measurement_id or 'AW-XXXXXXXXX'
        return f"""<!-- Google tag (gtag.js) — Dán vào <head> WordPress -->
<script async src="https://www.googletagmanager.com/gtag/js?id={mid}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{mid}');
</script>"""

    def _make_gtag_purchase_snippet(self):
        mid = self.measurement_id or 'AW-XXXXXXXXX'
        actions = self.conversion_action_ids.filtered(
            lambda a: a.action_type == 'purchase'
        )
        label = actions[0].conversion_label if actions else 'CONVERSION_LABEL'
        return f"""<?php
// Dán vào functions.php — Theo dõi đơn hàng với gtag trực tiếp
add_action('woocommerce_thankyou', 'hlv_gtag_purchase_event', 10, 1);
function hlv_gtag_purchase_event($order_id) {{
    $order = wc_get_order($order_id);
    ?>
    <script>
      gtag('event', 'conversion', {{
        'send_to': '{mid}/{label}',
        'value': <?php echo $order->get_total(); ?>,
        'currency': '<?php echo $order->get_currency(); ?>',
        'transaction_id': '<?php echo $order_id; ?>'
      }});
    </script>
    <?php
}}"""


    @api.depends('gtm_item_ids.ga4_event_count', 'gtm_item_ids.item_type', 'gtm_item_ids.tag_subtype')
    def _compute_ga4_dashboard(self):
        """Render giao diện Dashboard Đồ Thị (Horizontal Bar Chart) từ dữ liệu Event Count"""
        for rec in self:
            ga4_tags = rec.gtm_item_ids.filtered(lambda t: t.item_type == 'tag' and (t.tag_subtype == 'ga4_event' or 'GA4' in (t.name or '').upper()))
            
            if not ga4_tags:
                rec.ga4_dashboard_html = """
                    <div style="padding: 20px; text-align: center; color: #6b7280; background-color: #f9fafb; border-radius: 8px; border: 1px dashed #d1d5db;">
                        <i class="fa fa-bar-chart fa-3x" style="color: #e5e7eb; margin-bottom: 10px;"></i>
                        <p style="margin: 0; font-family: sans-serif;">Chưa có dữ liệu sự kiện GA4 nào được đồng bộ.</p>
                    </div>
                """
                continue

            # Sort by count desc
            sorted_tags = sorted(ga4_tags, key=lambda t: t.ga4_event_count, reverse=True)
            max_count = max(sorted_tags[0].ga4_event_count, 1) # Prevent div by 0

            html_lines = []
            html_lines.append("""
            <div style="background-color: #ffffff; border-radius: 12px; border: 1px solid #e5e7eb; padding: 20px; font-family: 'Inter', 'Segoe UI', sans-serif; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <h3 style="margin: 0; color: #111827; font-size: 16px; font-weight: 600;">📊 Lưu Lượng Sự Kiện (30 Ngày Qua)</h3>
                    <span style="font-size: 12px; color: #6b7280; font-weight: 500; background: #f3f4f6; padding: 4px 10px; border-radius: 12px;">Được đồng bộ từ Google Analytics 4</span>
                </div>
                <div style="display: flex; flex-direction: column; gap: 12px;">
            """)

            for tag in sorted_tags:
                count = tag.ga4_event_count
                percentage = min(int((count / max_count) * 100), 100) if max_count > 0 else 0
                
                # Màu sắc gradient tùy mức độ
                if percentage > 75:
                    bar_color = "linear-gradient(90deg, #3b82f6 0%, #2563eb 100%)" # Blue
                elif percentage > 40:
                    bar_color = "linear-gradient(90deg, #60a5fa 0%, #3b82f6 100%)" # Light Blue
                elif percentage > 10:
                    bar_color = "linear-gradient(90deg, #93c5fd 0%, #60a5fa 100%)" # Paler Blue
                else:
                    bar_color = "#e5e7eb" # Gray for very low/0

                html_lines.append(f"""
                    <div style="position: relative; width: 100%;">
                        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px;">
                            <span style="color: #374151; font-size: 13px; font-weight: 500; width: 40%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{tag.name}">{tag.name}</span>
                            <span style="color: #111827; font-size: 13px; font-weight: 600;">{count:,} <span style="font-weight: 400; color: #6b7280; font-size: 11px;">lượt</span></span>
                        </div>
                        <div style="width: 100%; height: 8px; background-color: #f3f4f6; border-radius: 4px; overflow: hidden;">
                            <div style="height: 100%; width: {percentage}%; background: {bar_color}; border-radius: 4px; transition: width 0.5s ease-in-out;"></div>
                        </div>
                    </div>
                """)

            html_lines.append("""
                </div>
            </div>
            """)
            
            rec.ga4_dashboard_html = "\n".join(html_lines)




class GoogleAdsConversionAction(models.Model):
    _name = 'google.ads.conversion.action'
    _description = 'Google Ads Conversion Action'
    _rec_name = 'name'

    tag_id = fields.Many2one(
        'google.ads.tag', string='Tag', required=True, ondelete='cascade',
    )
    name = fields.Char(string='Tên Action', required=True)
    action_type = fields.Selection([
        ('purchase', 'Mua Hàng'),
        ('contact',  'Liên Hệ'),
        ('signup',   'Đăng Ký'),
        ('lead',     'Lead Form'),
        ('pageview', 'Xem Trang'),
        ('custom',   'Tùy Chỉnh'),
    ], string='Loại Event', required=True, default='purchase')
    conversion_id = fields.Char(
        string='Conversion ID',
        help='Lấy từ Google Ads > Goals > Conversions (dạng số: 123456789)',
    )
    conversion_label = fields.Char(
        string='Conversion Label',
        help='Lấy từ Google Ads > Goals > Conversions (dạng: AbCdEfGhIjK)',
    )
