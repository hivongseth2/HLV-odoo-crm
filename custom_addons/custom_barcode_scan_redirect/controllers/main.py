# -*- coding: utf-8 -*-
from odoo import http, api, SUPERUSER_ID
from odoo.http import request
import logging, os, uuid, json, threading, tempfile, time, base64
from datetime import datetime
from base64 import b64encode
from werkzeug.utils import secure_filename
from werkzeug.wrappers import Response
from werkzeug.exceptions import BadRequest, NotFound, UnsupportedMediaType, RequestEntityTooLarge
from tempfile import NamedTemporaryFile
from markupsafe import Markup, escape

# PyDrive2 để upload My Drive
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.client import OAuth2Credentials   # dùng lại token đã cấp trong oauth flow
from werkzeug.utils import redirect

_logger = logging.getLogger(__name__)

# ====== Cấu hình upload trực tiếp (fallback) ======
ALLOWED_MIME = {'video/webm', 'video/mp4', 'video/ogg'}
MAX_UPLOAD_MB = 200

# ====== Khu lưu stream tạm theo CHUNK ======
STREAM_DIR = os.path.join(tempfile.gettempdir(), 'pack_streams')
os.makedirs(STREAM_DIR, exist_ok=True)

def _meta_path(upload_id):  return os.path.join(STREAM_DIR, f'{upload_id}.meta.json')
def _file_path(upload_id):  return os.path.join(STREAM_DIR, f'{upload_id}.webm')  # luôn nối đuôi kiểu nhị phân

# ====== Helper Google OAuth settings (endpoint v2) ======
G_AUTH_URI   = "https://accounts.google.com/o/oauth2/v2/auth"
G_TOKEN_URI  = "https://oauth2.googleapis.com/token"
G_REVOKE_URI = "https://oauth2.googleapis.com/revoke"

def _write_settings_file(settings_path, cid, csec, redir, scopes_line):
    scopes = [s.strip() for s in (scopes_line or '').replace(',', ' ').split() if s.strip()] \
             or ['https://www.googleapis.com/auth/drive.file']
    scopes_block = '\n'.join([f'  - {s}' for s in scopes])
    content = (
        "client_config_backend: settings\n"
        "client_config:\n"
        f"  client_id: \"{cid}\"\n"
        f"  client_secret: \"{csec}\"\n"
        f"  redirect_uri: \"{redir}\"\n"
        f"  auth_uri: \"{G_AUTH_URI}\"\n"
        f"  token_uri: \"{G_TOKEN_URI}\"\n"
        f"  revoke_uri: \"{G_REVOKE_URI}\"\n"
        "oauth_scope:\n"
        f"{scopes_block}\n"
        "get_refresh_token: True\n"
        "save_credentials: False\n"
    )
    with open(settings_path, 'w', encoding='utf-8') as f:
        f.write(content)

# ====== Background task: upload file -> Google Drive (My Drive) ======
def _bg_upload_to_drive(dbname, picking_id, filepath, mimetype):
    from odoo import registry as odoo_registry
    set_path = None
    try:
        with odoo_registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            ICP = env['ir.config_parameter'].sudo()

            _logger.info("BG_UPLOAD start db=%s pick=%s file=%s size=%s",
                         dbname, picking_id, filepath,
                         (os.path.getsize(filepath) if os.path.exists(filepath) else -1))

            creds_json = ICP.get_param('gdrive.user_credentials_json') or ''
            if not creds_json:
                _logger.error("BG_UPLOAD missing token")
                return

            cid   = ICP.get_param('gdrive.oauth_client_id') or ''
            csec  = ICP.get_param('gdrive.oauth_client_secret') or ''
            redir = ICP.get_param('gdrive.oauth_redirect_uri') or ''
            scopes_line = ICP.get_param('gdrive.oauth_scopes') or 'https://www.googleapis.com/auth/drive.file'
            
            # Lấy warehouse code từ picking
            picking = env['stock.picking'].sudo().browse(picking_id)
            warehouse_code = picking.location_id.warehouse_id.code or 'DEFAULT'
            
            # Mapping warehouse code -> folder name (dễ đọc)
            # Format: TSN:KHO_HCM,KBC:KHO_BENCAM
            mapping_str = ICP.get_param('gdrive.warehouse_folder_mapping') or 'TSN:KHO_HCM,KBC:KHO_BENCAM'
            warehouse_mapping = {}
            for item in mapping_str.split(','):
                if ':' in item:
                    code, folder = item.strip().split(':', 1)
                    warehouse_mapping[code.strip()] = folder.strip()
            
            # Lấy folder name từ mapping, fallback về warehouse code
            root_name = warehouse_mapping.get(warehouse_code, f'KHO_{warehouse_code}')
            
            anyone_link = (ICP.get_param('gdrive.anyone_link') or 'false').lower() == 'true'
            # order
            order_name = ''
            try:
                order_name = picking.sale_id.name or ''
            except Exception:
                pass
            if not order_name:
                order_name = (picking.origin or picking.group_id.name or '')
            # pick
            origin_pick = env['stock.picking'].sudo().search([
                ('group_id', '=', picking.group_id.id),
                ('picking_type_id.sequence_code', 'like', 'PICK'),
                ('id', '!=', picking.id),
            ], limit=1)
            origin_name = (origin_pick.name or '').replace('/', '_').replace('\\', '_')
                
            
            def _san(s): return (s or '').replace('/', '_').replace('\\', '_').replace(' ', '_')


            # ext theo mimetype
            if mimetype == 'video/webm':   ext = '.webm'
            elif mimetype == 'video/mp4':  ext = '.mp4'
            elif mimetype == 'video/ogg':  ext = '.ogg'
            else:                          ext = os.path.splitext(filepath)[1] or '.webm'

            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            # safe_title = f"pack_{origin_name}_{picking.name}_{ts}{ext}".replace(' ', '_').replace('/', '_').replace('\\', '_')
            safe_title = f"{_san(order_name)}_{_san(origin_name)}_{_san(picking.name)}_{ts}{ext}"


            # settings tạm
            set_path = os.path.join(STREAM_DIR, f'settings_{uuid.uuid4().hex}.yaml')
            _write_settings_file(set_path, cid, csec, redir, scopes_line)

            # auth
            gauth = GoogleAuth(set_path)
            gauth.credentials = OAuth2Credentials.from_json(creds_json)
            try:
                if gauth.access_token_expired:
                    _logger.info("BG_UPLOAD token expired -> refresh")
                    gauth.Refresh()
                gauth.Authorize()  # <<< bắt buộc đảm bảo HTTP client
            except Exception:
                _logger.exception("BG_UPLOAD refresh/authorize failed")
                return

            drive = GoogleDrive(gauth)

            # folders
            def _list(q): return drive.ListFile({'q': q}).GetList()
            def _get_or_create_folder(name, parent_id=None):
                q = "mimeType='application/vnd.google-apps.folder' and trashed=false and title='%s'" % name.replace("'", "\\'")
                if parent_id: q += f" and '{parent_id}' in parents"
                found = _list(q)
                if found: return found[0]['id']
                meta = {'title': name, 'mimeType': 'application/vnd.google-apps.folder'}
                if parent_id: meta['parents'] = [{'id': parent_id}]
                f = drive.CreateFile(meta); f.Upload(); return f['id']

            root_id = _get_or_create_folder(root_name, None)
            day_id  = _get_or_create_folder(datetime.now().strftime("%d_%m_%Y"), root_id)
            clip_id = _get_or_create_folder("clip", day_id)

            _logger.info("BG_UPLOAD uploading title=%s -> folder=%s", safe_title, clip_id)
            gfile = drive.CreateFile({'title': safe_title, 'parents': [{'id': clip_id}]})
            if mimetype: gfile['mimeType'] = mimetype
            gfile.SetContentFile(filepath)
            gfile.Upload()

            fid = gfile['id']
            link = gfile.get('alternateLink') or f"https://drive.google.com/file/d/{fid}/view"

            if anyone_link:
                try:
                    gfile.InsertPermission({'type': 'anyone', 'value': 'me', 'role': 'reader'})
                except Exception:
                    _logger.warning("BG_UPLOAD set public link failed", exc_info=True)
                    
            
            fid = gfile['id']
            link = gfile.get('alternateLink') or f"https://drive.google.com/file/d/{fid}/view"

            # if picking.exists():
           
            #     picking.message_post(
            #     body=f"📹 Video đóng gói: <a href='{link}' target='_blank'>{safe_title}</a>"
            #         )


            # ... sau khi đã có: fid, link, safe_title
            if picking.exists():
                # Tạo body HTML an toàn: escape title & url, rồi wrap bằng Markup
                body = Markup(
                    '📹 Video đóng gói: '
                    '<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
                ).format(url=escape(link or ''), title=escape(safe_title or 'Video'))

                picking.message_post(
                    body=body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )

            _logger.info("✅ BG_UPLOAD ok: %s (%s) %s", safe_title, fid, link)

    except Exception:
        _logger.exception("BG_UPLOAD fatal")
    finally:
        try: os.remove(filepath)
        except: pass
        if set_path:
            try: os.remove(set_path)
            except: pass

class CustomBarcodeScanController(http.Controller):
    
    def _get_ml_demand(self, ml):
        """
        [V3.6] Helper lấy số lượng yêu cầu (planned) cho một move_line.
        Khi quét phiếu PICK để vào phiếu PACK, Odoo thường để reserved_qty = 0 ở phiếu PACK.
        Ta phải tìm ngược lại quantity ở dòng tương ứng của phiếu PICK.
        """
        # 1. Ưu tiên lấy từ reservation trực tiếp của dòng (nếu có)
        res = getattr(ml, 'reserved_qty', 0) or getattr(ml, 'reserved_uom_qty', 0) or getattr(ml, 'product_uom_qty', 0) or 0
        if res > 0:
            return res
            
        # 2. Nếu là dòng có package_id (kiện hàng từ bước trước chuyển sang)
        if ml.package_id:
            # Truy vết qua move_orig_ids (các phiếu nguồn, thường là PICK)
            orig_mls = ml.move_id.move_orig_ids.mapped('move_line_ids').filtered(
                lambda l: l.result_package_id.id == ml.package_id.id and l.product_id.id == ml.product_id.id
            )
            if orig_mls:
                total = 0.0
                for ol in orig_mls:
                    # Odoo 17 dùng quantity, Odoo cũ dùng qty_done (ta lấy cả 2 cho chắc)
                    total += getattr(ol, 'quantity', 0) or getattr(ol, 'qty_done', 0) or 0
                return total
                
        return 0


    # ===================== UI & SCAN luồng sẵn có =====================
    @http.route(['/custom_barcode_scan/ui'], type='http', auth='user')
    def scan_ui(self):
        return request.render("custom_barcode_scan_redirect.scan_ui_template")

    @http.route('/custom_barcode_scan/ui/scan', type='json', auth='user', csrf=False)
    def scan_ui_api(self, **kwargs):
        _logger = logging.getLogger(__name__)
        barcode = kwargs.get("barcode")
        _logger.info(f"[SCAN] Barcode: {barcode}")

        Picking = request.env['stock.picking'].sudo()
        picking = Picking.search([('name', '=', barcode)], limit=1)

        if not picking:
            return {'type': 'ir.actions.client','tag': 'display_notification','params': {
                'message': f"Không tìm thấy phiếu với mã: {barcode}", 'type': 'danger','sticky': False}}

        if picking.state == 'done' and picking.group_id:
            _logger.info(picking.picking_type_id.read()[0])

            # Lấy tất cả PACK còn xử lý được
            packs = Picking.search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('picking_type_id.sequence_code', 'like', 'PACK'),
                ('state', 'in', ['confirmed', 'assigned', 'waiting', 'in_progress']),
            ])

            # Ưu tiên 'assigned' trước
            def _priority(p):
                # assigned → 0 (cao nhất), in_progress → 1, confirmed/waiting → 2
                s = (p.state or '')
                if s == 'assigned': return (0, p.id)
                if s == 'in_progress': return (1, p.id)
                return (2, p.id)

            packs_sorted = sorted(packs, key=_priority)
            
            # [NEW] Nếu có nhiều phiếu -> Trả về danh sách để user chọn
            if len(packs_sorted) > 1:
                return {
                    'type': 'custom_pack_selection',
                    'title': f"Tìm thấy {len(packs_sorted)} phiếu PACK cho {picking.name}",
                    'items': [{
                        'id': p.id,
                        'name': p.name,
                        'state': dict(p._fields['state'].selection).get(p.state, p.state),
                        'date': p.scheduled_date and p.scheduled_date.strftime('%d/%m') or ''
                    } for p in packs_sorted]
                }

            next_picking = packs_sorted and packs_sorted[0] or False

            if next_picking:
                # nếu gặp loại "outgoing" thì chỉ báo (giữ nguyên ý cũ)
                if next_picking.picking_type_id.code == 'outgoing':
                    return {
                        'type': 'ir.actions.client','tag': 'display_notification','params': {
                            'message': f"✅ Phiếu {picking.name} đã hoàn tất! Đang chờ xuất kho...",
                            'type': 'info','sticky': False
                        }
                    }
                else:
                    return {
                        'type': 'ir.actions.act_url',
                        'url': f"/custom_barcode_scan/pack_view/{next_picking.id}",
                        'target': 'self'
                    }

            return {
                'type': 'ir.actions.client','tag': 'display_notification','params': {
                    'message': "Không tìm thấy phiếu PACK phù hợp để xử lý!",
                    'type': 'warning','sticky': False
                }
            }


        return self._get_barcode_action(picking.id)

    def _get_barcode_action(self, picking_id):
        _logger = logging.getLogger(__name__)
        Picking = request.env['stock.picking'].sudo()
        picking = Picking.browse(picking_id)

        if not picking.exists():
            return {'type': 'ir.actions.client','tag': 'display_notification','params': {
                'message': f"Phiếu #{picking_id} không tồn tại.",'type': 'danger','sticky': False}}

        if not picking.picking_type_id:
            return {'type': 'ir.actions.client','tag': 'display_notification','params': {
                'message': "Phiếu không có loại chuyển kho, không thể mở giao diện barcode.",'type': 'danger','sticky': False}}

        _logger.info(f"[ACTION] Gửi barcode_action cho phiếu: {picking.name} | Picking Type: {picking.picking_type_id.name}")
        if picking.picking_type_id.code not in ['out', 'pick']:
            return {'type': 'ir.actions.client','tag': 'display_notification','params': {
                'message': f"Phiếu {picking.name} không thuộc loại Pick hoặc Out. Không thể mở giao diện barcode.",'type': 'warning','sticky': False}}

        action = request.env.ref('stock_barcode.stock_barcode_picking_client_action').sudo().read()[0]
        action.update({'context': {'active_id': picking.id,'default_picking_type_id': picking.picking_type_id.id,
                                   'res_model': 'stock.picking','res_id': picking.id}})
        return action

    @http.route('/custom_barcode_scan/pack_view/<int:picking_id>', type='http', auth='user')
    def view_pack_products(self, picking_id):
        _logger = logging.getLogger(__name__)
        _logger.info(f"🔍 Đang vào pack_view với ID: {picking_id}")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            _logger.error("❌ Không tìm thấy phiếu pack!")
            return request.not_found()

        # [V3.7] Auto-assign: Nếu phiếu PACK chưa được assign, tự động gọi action_assign
        # để Odoo propagate packages từ PICK sang PACK
        if picking.state in ['confirmed', 'waiting']:
            try:
                _logger.info(f"[PACK_VIEW] Auto-assigning picking {picking.name} (state: {picking.state})")
                picking.action_assign()
                # Reload picking để lấy data mới sau assign
                picking = request.env['stock.picking'].sudo().browse(picking_id)
                _logger.info(f"[PACK_VIEW] After assign: state={picking.state}, move_lines={len(picking.move_line_ids)}")
            except Exception as e:
                _logger.warning(f"[PACK_VIEW] Auto-assign failed: {e}")

        lines = picking.move_ids_without_package.filtered(lambda m: m.product_id)

        # Tìm PICK gốc để hiển thị
        origin_pick = request.env['stock.picking'].sudo().search([
            ('group_id', '=', picking.group_id.id),
            ('picking_type_id.sequence_code', 'like', 'PICK'),
            ('id', '!=', picking.id)
        ], limit=1)

        drive_connected = bool(request.env['ir.config_parameter'].sudo().get_param('gdrive.user_credentials_json'))

        # ✨ NEW: Lấy tất cả PACK còn xử lý được để show panel chọn nhanh
        siblings = request.env['stock.picking'].sudo().search([
            ('group_id', '=', picking.group_id.id),
            ('picking_type_id.sequence_code', 'like', 'PACK'),
            ('id', '!=', picking.id),
            ('state', 'in', ['confirmed', 'assigned', 'waiting', 'in_progress']),
        ])

        def _priority(p):
            s = (p.state or '')
            if s == 'assigned': return (0, p.id)
            if s == 'in_progress': return (1, p.id)
            return (2, p.id)

        siblings_sorted = sorted(siblings, key=_priority)

        state_label = {
            'draft': 'Nháp',
            'waiting': 'Chờ',
            'confirmed': 'Xác nhận',
            'assigned': 'Sẵn sàng',
            'in_progress': 'Đang làm',
            'done': 'Hoàn tất',
            'cancel': 'Hủy',
        }

        sibling_packs = [{
            'id': s.id,
            'name': s.name,
            'state': s.state,
            'state_label': state_label.get(s.state, s.state),
        } for s in siblings_sorted]

        # Lấy danh sách packages của picking hiện tại (bao gồm cả package từ PICK và package tạo mới)
        picking_packages = []
        
        # 1. Lấy packages từ phiếu PACK hiện tại
        all_pkgs = (picking.move_line_ids.mapped('result_package_id') | picking.move_line_ids.mapped('package_id'))
        
        # 2. [V3.7] Truy vết packages từ phiếu PICK gốc qua move_orig_ids
        # Khi PICK đóng gói và validate, packages nằm ở result_package_id của PICK's move_lines
        origin_pkgs = request.env['stock.quant.package'].sudo()
        origin_pkg_mls_map = {}  # Lưu mapping package_id -> move_lines từ origin
        
        for move in picking.move_ids:
            for orig_move in move.move_orig_ids:
                for orig_ml in orig_move.move_line_ids:
                    if orig_ml.result_package_id:
                        origin_pkgs |= orig_ml.result_package_id
                        pkg_id = orig_ml.result_package_id.id
                        if pkg_id not in origin_pkg_mls_map:
                            origin_pkg_mls_map[pkg_id] = request.env['stock.move.line'].sudo()
                        origin_pkg_mls_map[pkg_id] |= orig_ml
        
        # 3. Gộp tất cả packages (loại bỏ trùng lặp do toán tử |)
        all_pkgs = all_pkgs | origin_pkgs
        
        _logger.info(f"[PACK_VIEW] Picking {picking.name}: Found {len(all_pkgs)} packages (local + origin)")
        
        if all_pkgs:
            for pkg in all_pkgs:
                # Lọc các dòng thuộc package này từ PACK hiện tại
                pkg_mls = picking.move_line_ids.filtered(lambda ml: ml.result_package_id.id == pkg.id or ml.package_id.id == pkg.id)
                
                # [V3.7] Nếu không có move_lines từ PACK, lấy từ origin PICK
                is_from_origin = False
                if not pkg_mls and pkg.id in origin_pkg_mls_map:
                    pkg_mls = origin_pkg_mls_map[pkg.id]
                    is_from_origin = True
                    _logger.info(f"[PACK_VIEW] Package {pkg.name} loaded from origin PICK with {len(pkg_mls)} lines")
                
                if not pkg_mls:
                    continue
                
                # Tính qty: nếu từ origin thì lấy quantity/qty_done từ PICK
                if is_from_origin:
                    total_qty = sum(getattr(ml, 'quantity', 0) or getattr(ml, 'qty_done', 0) or 0 for ml in pkg_mls)
                    package_lines = [{
                        'product_name': ml.product_id.display_name,
                        'product_qty': getattr(ml, 'quantity', 0) or getattr(ml, 'qty_done', 0) or 0,
                        'product_uom': ml.product_uom_id.name,
                        'reserved_qty': getattr(ml, 'quantity', 0) or getattr(ml, 'qty_done', 0) or 0,
                    } for ml in pkg_mls]
                else:
                    total_qty = sum(ml.qty_done for ml in pkg_mls)
                    package_lines = [{
                        'product_name': ml.product_id.display_name,
                        'product_qty': ml.qty_done,
                        'product_uom': ml.product_uom_id.name,
                        # [V3.6] Hiển thị reservation thông minh (truy vết từ PICK nếu cần)
                        'reserved_qty': self._get_ml_demand(ml),
                    } for ml in pkg_mls]
                
                picking_packages.append({
                    'id': pkg.id,
                    'name': pkg.name,
                    'qty': total_qty,
                    'package_lines': package_lines,
                    'is_from_origin': is_from_origin,  # Flag để UI biết đây là package từ PICK
                })

        return request.render("custom_barcode_scan_redirect.pack_scan_template", {
            'picking': picking,
            'lines': lines,
            'origin_pick_name': origin_pick.name if origin_pick else '',
            'drive_connected': drive_connected,
            'sibling_packs': sibling_packs,
            'picking_packages': picking_packages,
        })



    @http.route('/pack_scan/scan_item', type='json', auth='user')
    def scan_pack_item(self, **kwargs):
        picking_id = kwargs.get("picking_id")
        barcode = kwargs.get("barcode")
        delta = float(kwargs.get("delta", 1))
        line_id = kwargs.get("line_id")
        move_id = kwargs.get("move_id")
        _logger = logging.getLogger(__name__)
        _logger.info(f"SCAN_ITEM START: barcode={barcode}, delta={delta}, line_id={line_id}, move_id={move_id}")
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        # Tìm move dựa trên barcode
        # [FIX] Use move_ids instead of move_ids_without_package to ensure we see ALL moves
        # move_ids_without_package is a UI helper field that might hide some moves depending on context
        moves = picking.move_ids.filtered(lambda m: m.product_id.barcode == barcode)
        
        # [FIX] Sort moves by Size (Demand) DESCENDING to prevent "Small Move First" overflow issues.
        # e.g. If Moves are [10, 40] and we scan 40.
        # If we check 10 first -> Update 10 -> 40/10 (Overflow).
        # If we check 40 first -> Update 40 -> 40/40 (Perfect).
        moves = moves.sorted(key=lambda m: (m.product_uom_qty, m.id), reverse=True)
        
        if not moves:
            return {"error": "❌ Mã sản phẩm không khớp trong phiếu!"}
        # Tính tổng quát để check xem đã đủ hết chưa
        total_required = sum(m.product_uom_qty for m in moves)
        total_done = sum(sum(ml.qty_done for ml in m.move_line_ids) for m in moves)
        if delta > 0 and total_done >= total_required:
            return {"error": "⚠️ Sản phẩm này đã được quét đủ!"}
        updated_lines = []
        
        # [NEW QUICK CHECK] Chặn quét nếu kho không đủ hàng (product_type = consu/consu)
        product = moves[0].product_id
        loc_id = moves[0].location_id.id
        if product.type in ['product', 'consu'] and product.with_context(location=loc_id).qty_available <= 0:
            return {"error": f"⚠️ Sản phẩm {product.display_name} hiện không có tồn kho thực tế tại {moves[0].location_id.display_name}!"}
            
        # --- LOGIC MỚI: Xử lý tìm line_id tự động nếu FE gửi lên null ---
        # Lấy line_id cụ thể từ FE nếu có
        target_ml = None
        if line_id:
            try:
                target_ml = request.env['stock.move.line'].sudo().browse(int(line_id))
                if not target_ml.exists():
                    target_ml = None
            except:
                target_ml = None

        # [FIX] Tìm target_move từ move_id (nếu FE gửi lên) để scope lại tìm kiếm
        target_move_from_fe = None
        if move_id:
            try:
                target_move_from_fe = request.env['stock.move'].sudo().browse(int(move_id))
                if not target_move_from_fe.exists() or target_move_from_fe.picking_id.id != picking.id:
                    target_move_from_fe = None
            except:
                target_move_from_fe = None

        if target_ml:
            # [SMART-REDIRECT-2024-V3.4] Logic lấp đầy toàn diện (Universal Balanced)
            # Cho phép Redirect ngay cả khi target_ml đã gắn package 
            is_target_packed = target_ml.result_package_id or target_ml.package_id
            target_res = getattr(target_ml, 'reserved_qty', 0) or getattr(target_ml, 'reserved_uom_qty', 0) or 0
            
            # Chỉ redirect nếu: 
            # 1. Target là hàng lẻ
            # 2. HOẶC Target là package nhưng không có giới hạn (Reserved=0) và đã có hàng (Done > 0)
            if not is_target_packed or (target_res == 0 and target_ml.qty_done > 0):
                # [FIX] Khi có move_id, chỉ tìm trong cùng 1 stock.move để không nhảy sang dòng khác
                if target_move_from_fe:
                    all_product_mls = target_move_from_fe.move_line_ids.filtered(
                        lambda l: l.product_id.id == target_ml.product_id.id
                    )
                else:
                    all_product_mls = picking.move_line_ids.filtered(
                        lambda l: l.product_id.id == target_ml.product_id.id
                    )
                
                # Thứ tự ưu tiên V3.4:
                # 1. Dòng PACKAGE còn chỗ (qty_done < reserved)
                # 2. Dòng PACKAGE rỗng (qty_done == 0)
                # 3. Dòng HÀNG LẺ (Loose) còn chỗ hoặc rỗng
                
                # Sắp xếp các dòng để tìm ứng viên tốt nhất:
                # - Ưu tiên hàng có GẮN PACKAGE (package_id hoặc result_package_id) trước hàng lẻ
                # - Ưu tiên dòng có RESERVED_QTY > 0
                # - Ưu tiên dòng rỗng DONE == 0
                def get_prio(l):
                    is_pkg = bool(l.package_id or l.result_package_id)
                    # [V3.6] Dùng _get_ml_demand để nhận diện đúng nhu cầu của kiện từ PICK
                    res = self._get_ml_demand(l)
                    is_empty = (l.qty_done == 0)
                    # Trả về tuple (is_pkg, res_exists, is_empty, id) để sort
                    return (is_pkg, res > 0, is_empty, -l.id)

                sorted_mls = sorted(all_product_mls, key=get_prio, reverse=True)
                
                candidate = None
                # Bước 1: Tìm dòng PACKAGE còn chỗ hoặc rỗng
                for l in sorted_mls:
                    is_pkg = bool(l.package_id or l.result_package_id)
                    # [V3.6] Dùng _get_ml_demand
                    res = self._get_ml_demand(l)
                    if is_pkg:
                        if (res > 0 and l.qty_done < res) or (res == 0 and l.qty_done == 0):
                            candidate = l
                            _logger.info(f"REDIRECT V3.6 FOUND (Package Match): ML {l.id} | Package: {l.package_id.name or l.result_package_id.name}")
                            break
                
                # Bước 2: Nếu các kiện đã "tạm đủ" (mỗi kiện ít nhất 1 cái), tìm dòng HÀNG LẺ
                if not candidate:
                    for l in sorted_mls:
                        is_pkg = bool(l.package_id or l.result_package_id)
                        if not is_pkg: # Hàng lẻ
                             candidate = l
                             _logger.info(f"REDIRECT V3.4 FOUND (Loose Line Match): ML {l.id} | No Package")
                             break
                
                if candidate:
                    _logger.info(f"REDIRECT V3.4 EXECUTE: ML {target_ml.id} -> ML {candidate.id}")
                    target_ml = candidate

            if delta > 0:
                # [FIX-2024] Kiểm tra nếu dòng trong pack VẪN CÒN CHỖ
                # Nếu reserved_qty = 0 (trường hợp pre-configured từ PICK), ta coi như chưa giới hạn chỗ trong pack
                # nhưng vẫn phải tôn trọng tổng demand của Move.
                mv = target_ml.move_id
                mv_done = sum(l.qty_done for l in mv.move_line_ids)
                
                # [V3.6] Check reserved qty của chính line này
                reserved_qty = self._get_ml_demand(target_ml)
                
                # Cả package_id (từ PICK) và result_package_id (đóng gói mới) đều được coi là "hàng trong pack"
                is_packed = target_ml.result_package_id or target_ml.package_id
                
                if mv_done >= mv.product_uom_qty:
                    _logger.info(f"Target line {target_ml.id} belongs to FULL Move {mv.id} ({mv_done}/{mv.product_uom_qty}). Switching to find another.")
                    target_ml = None
                elif is_packed and reserved_qty > 0 and target_ml.qty_done >= reserved_qty:
                    # Chỉ coi là FULL nếu có đặt reservation (>0) và đã đạt mức đó.
                    # Nếu reservation = 0, ta cho phép điền vào (vì logic Redirect đã chọn nó làm ứng viên).
                    _logger.info(f"Target line {target_ml.id} is packed ({is_packed.name}) and reaches Reserved Qty ({reserved_qty}). Skipping.")
                    target_ml = None
                elif target_ml.result_package_id and reserved_qty == 0 and target_ml.qty_done > 0:
                    # [FIX-2024] Dòng đã đóng gói xong (ko dự kiến) thì không tự động độn thêm khi scan hàng lẻ.
                    _logger.info(f"Target line {target_ml.id} is already fully packed with no reserved qty. Skipping.")
                    target_ml = None
                else:
                    _logger.info(f"Target line {target_ml.id} is valid (Space: {target_ml.qty_done}/{reserved_qty} | Move: {mv_done}/{mv.product_uom_qty}). Keeping it.")

        # Nếu chưa xác định được target_ml (do line_id null hoặc sai hoặc đã bị packed), tự động tìm dòng phù hợp
        if not target_ml:
            # [FIX] Khi có move_id từ FE, chỉ tìm trong move đó trước
            scoped_moves = moves
            if target_move_from_fe and target_move_from_fe in moves:
                scoped_moves = target_move_from_fe
            
            if delta > 0:
                # Thu thập move_lines (scope theo move_id nếu có)
                all_move_lines = request.env['stock.move.line'].sudo()
                for m in scoped_moves:
                    all_move_lines |= m.move_line_ids
                
                # [FIX-2024] Sắp xếp: Ưu tiên các dòng đã được liên kết với package (nguồn hoặc đích)
                # Điều này giúp điền đầy các dòng "pre-configured" trước khi tìm đến dòng lẻ.
                all_move_lines = all_move_lines.sorted(key=lambda ml: (bool(ml.result_package_id or ml.package_id), ml.id), reverse=True)
                
                _logger.info(f"DEBUG_MOVE_LINES: Found {len(all_move_lines)} move_lines for barcode {barcode}. IDs: {all_move_lines.ids}")
                
                found_target = False
                candidate_open_move = None  # Move có dư demand nhưng chưa có line phù hợp
                
                for ml in all_move_lines:
                    # Lấy reserved_qty (product_uom_qty) hoặc reserved_uom_qty tùy version Odoo
                    # Trong Odoo 16+, có trường reserved_qty hoặc product_uom_qty trên move_line
                    reserved_qty = getattr(ml, 'reserved_qty', 0) or getattr(ml, 'reserved_uom_qty', 0) or getattr(ml, 'product_uom_qty', 0) or 0
                    remaining_in_line = reserved_qty - ml.qty_done
                    
                    _logger.info(f"CHECK MOVE_LINE {ml.id}: Move={ml.move_id.id}, Reserved={reserved_qty}, Done={ml.qty_done}, Remain={remaining_in_line}, PackageId={ml.package_id.id if ml.package_id else 'None'}, ResultPkg={ml.result_package_id.id if ml.result_package_id else 'None'}")
                    
                    # [FIX-2024] Điều kiện: move_line còn chỗ. 
                    # Không check result_package_id để hỗ trợ các dòng được gán package sẵn (pre-configured)
                    if remaining_in_line > 0:
                        target_ml = ml
                        _logger.info(f"Selected move_line {ml.id} (Packed: {bool(ml.result_package_id)}) with remaining {remaining_in_line}")
                        found_target = True
                        break
                    
                    # Nếu đã được đóng gói nhưng còn chỗ -> bỏ qua (user phải sửa trong package)
                    # Nếu chưa đóng gói nhưng đã full -> bỏ qua, tìm dòng tiếp theo
                
                # Nếu không tìm thấy move_line nào còn chỗ, kiểm tra xem move có dư demand không
                if not found_target:
                    for m in scoped_moves:
                        move_done = sum(ml.qty_done for ml in m.move_line_ids)
                        move_remaining = m.product_uom_qty - move_done
                        if move_remaining > 0:
                            candidate_open_move = m
                            _logger.info(f"Move {m.id} has remaining demand {move_remaining}. Will create new line.")
                            break
                
                # Tạo line mới nếu cần
                if not found_target and candidate_open_move:
                    _logger.info(f"Creating new line for Move {candidate_open_move.id}")
                    try:
                        target_ml = request.env['stock.move.line'].sudo().create({
                            'picking_id': picking.id,
                            'move_id': candidate_open_move.id,
                            'product_id': candidate_open_move.product_id.id,
                            'product_uom_id': candidate_open_move.product_uom.id,
                            'location_id': candidate_open_move.location_id.id,
                            'location_dest_id': candidate_open_move.location_dest_id.id,
                            'qty_done': 0,
                        })
                        found_target = True
                        _logger.info(f"Created new line for Move {candidate_open_move.id}: {target_ml.id}")
                    except Exception as e:
                        _logger.error(f"Failed to create move line: {e}")
                        return {"error": "❌ Lỗi hệ thống: Không thể tạo dòng sản phẩm mới."}

                # Fallback: tìm loose line (scope theo move_id nếu có)
                if not found_target:
                    _logger.info("All move_lines are full or packed. Fallback to find any loose line.")
                    loose_candidates = request.env['stock.move.line'].sudo().search([
                        ('picking_id', '=', picking.id),
                        ('product_id', 'in', scoped_moves.mapped('product_id').ids),
                        ('move_id', 'in', scoped_moves.ids),
                        ('result_package_id', '=', False)
                    ], limit=1)
                    
                    if loose_candidates:
                        target_ml = loose_candidates[0]
                        _logger.info(f"Fallback: Found generic loose line: {target_ml.id}")
                    elif scoped_moves:
                        # Tạo line mới cho move đầu tiên (over-scan)
                        m = scoped_moves[0] if hasattr(scoped_moves, '__getitem__') else scoped_moves
                        try:
                            target_ml = request.env['stock.move.line'].sudo().create({
                                'picking_id': picking.id,
                                'move_id': m.id,
                                'product_id': m.product_id.id,
                                'product_uom_id': m.product_uom.id,
                                'location_id': m.location_id.id,
                                'location_dest_id': m.location_dest_id.id,
                                'qty_done': 0,
                            })
                            _logger.info(f"Fallback: Created new line for Move {m.id}: {target_ml.id}")
                        except:
                            return {"error": "❌ Cannot create fallback line."}

            # Nếu đang trừ: tìm dòng có qty_done > 0
            elif delta < 0:
                for move in scoped_moves:
                    for ml in move.move_line_ids:
                        if ml.qty_done > 0:
                            # [VALIDATION] Check if line is already packed
                            # CHỈ trừ dòng chưa đóng gói. Dòng đã đóng gói KHÔNG được trừ ở đây.
                            if ml.result_package_id:
                                continue 
                            target_ml = ml
                            break
                    if target_ml: break
        
        # [Fallback] Nếu chưa tìm thấy target_ml và delta < 0, có thể do TOÀN BỘ đã đóng gói
        if not target_ml and delta < 0:
             # Check xem có dòng nào có thể trừ được không (kể cả đã pack) để báo lỗi chính xác
             has_packed_items = False
             for move in moves:
                 for ml in move.move_line_ids:
                     if ml.qty_done > 0 and ml.result_package_id:
                         has_packed_items = True
                         break
             if has_packed_items:
                 return {"error": "⚠️ Sản phẩm nằm trong kiện. Vui lòng vào chi tiết kiện để xóa!"}
        
        # --- THỰC HIỆN CẬP NHẬT ---
        if target_ml:
            # Reload để đảm bảo data mới nhất
            ml = target_ml
            current_qty = ml.qty_done
            
            # Tính toán lại giới hạn trên move cha của line này
            move = ml.move_id
            
            # [NEW] Lấy reserved_qty của move_line cụ thể này
            ml_reserved_qty = getattr(ml, 'reserved_qty', 0) or getattr(ml, 'reserved_uom_qty', 0) or getattr(ml, 'product_uom_qty', 0) or 0
            ml_remaining = max(0, ml_reserved_qty - current_qty)
            
            # [FIX] Move total done nên tính cả các line khác của move này
            move_total_done = sum(l.qty_done for l in move.move_line_ids)
            move_remain = max(0, move.product_uom_qty - move_total_done)
            
            _logger.info(f"Updating line {ml.id}. Current: {current_qty}. ML Reserved: {ml_reserved_qty}. ML Remain: {ml_remaining}. Move Total: {move_total_done}. Move Remain: {move_remain}")

            if delta > 0:
                # [NEW LOGIC] Chỉ cộng phần còn thiếu của move_line này
                # Điều này đảm bảo mỗi move_line được fill đúng reserved_qty của nó
                # Nếu ml_remaining = 0 mà vẫn scan -> Tìm dòng tiếp theo (logic ở trên đã xử lý)
                
                if ml_remaining > 0:
                    add_qty = min(delta, ml_remaining)
                else:
                    # Fallback: nếu move_line đã full nhưng move còn chỗ -> cộng vào move_remain
                    add_qty = min(delta, move_remain) if move_remain > 0 else delta
                
                if add_qty > 0:
                    # [NEW] Kiểm tra tồn kho khả dụng/thực tế TẠI VỊ TRÍ ĐÓ trước khi cho phép qty_done tăng thêm
                    # Bỏ qua kiểm tra nếu vị trí nguồn là location ảo (loại bỏ qua tồn kho)
                    if ml.location_id.usage == 'internal':
                        try:
                            quant = request.env['stock.quant'].sudo().search([
                                ('product_id', '=', move.product_id.id),
                                ('location_id', '=', ml.location_id.id)
                            ], limit=1)
                            
                            # Lấy ra số lượng vật lý tồn thật ở vị trí này.
                            available_in_loc = quant.quantity if quant else 0
                            
                            # Kiểm tra TỔNG số lượng đã lấy TƯƠNG ĐƯƠNG TRÊN TẤT CẢ CÁC PHIẾU CHƯA HOÀN THÀNH
                            # để xem việc quét thêm add_qty có làm vỡ kho không.
                            domain = [
                                ('product_id', '=', move.product_id.id),
                                ('location_id', '=', ml.location_id.id),
                                ('state', 'not in', ['done', 'cancel'])
                            ]
                            all_lines_in_loc = request.env['stock.move.line'].search(domain)
                            total_done_in_loc = sum(l.qty_done for l in all_lines_in_loc)
                            
                            if total_done_in_loc + add_qty > available_in_loc + 0.001:
                                return {"error": f"⚠️ Vị trí {ml.location_id.display_name} không đủ tồn! (Hệ thống đang quét: {total_done_in_loc}, Muốn lấy thêm: {add_qty}. Kho chỉ có: {available_in_loc})"}
                        except Exception as e:
                            _logger.error(f"Lỗi khi kiểm tra tồn kho: {e}")
                
                    new_qty = current_qty + add_qty
                    ml.write({'qty_done': new_qty})
                    
                    # [FIX] Calculate LOCAL Total Done for this specific Move (Line) 
                    # Frontend expects the quantity for this specific line item
                    
                    # 1. Total Done for this MOVE
                    local_done_qty = sum(l.qty_done for l in move.move_line_ids)

                    # 2. Packed Qty for this MOVE
                    # Only count lines in this move that have a result_package_id
                    local_packed_qty = sum(l.qty_done for l in move.move_line_ids if l.result_package_id)
                    
                    _logger.info(f"Updated Done Qty: {new_qty}. Local Total: {local_done_qty}. Local Packed: {local_packed_qty}")

                    updated_lines.append({
                        "line_id": ml.id,
                        "move_id": move.id,
                        "product": move.product_id.display_name,
                        "done_qty": local_done_qty,   # Return LOCAL total for this move
                        "packed_qty": local_packed_qty, # Return LOCAL packed for this move
                        "required_qty": move.product_uom_qty, # Return LOCAL required for this move
                        "barcode": move.product_id.barcode 
                    })
            
            elif delta < 0:
                reduce_qty = min(abs(delta), current_qty)
                if reduce_qty > 0:
                    new_qty = current_qty - reduce_qty
                    ml.write({'qty_done': new_qty})
                    
                    new_total_done_all = sum(l.qty_done for l in move.move_line_ids)
                    
                    updated_lines.append({
                        "line_id": ml.id,
                        "move_id": move.id,
                        "product": move.product_id.display_name,
                        "done_qty": new_total_done_all,
                        "required_qty": move.product_uom_qty,
                        "barcode": move.product_id.barcode
                    })
        
        _logger.info(f"Returning updated_lines: {len(updated_lines)}")
        if not updated_lines:
            # Trường hợp delta > 0 nhưng không tìm thấy dòng nào còn thiếu (dù check tổng ở trên đã pass)
            # Có thể do logic phân bổ move_line phức tạp, ta báo lỗi hoặc ignore
            return {"error": "⚠️ Không tìm thấy dòng sản phẩm phù hợp để cập nhật! Có thể sản phẩm đã được đóng gói, vui lòng chỉnh sửa trong giao diện đóng gói!"}
        return {"scanned": updated_lines}


    @http.route('/pack_scan/complete_picking', type='json', auth='user')
    def complete_pack_picking(self, **kwargs):
        picking_id = kwargs.get("picking_id")
        picking = request.env['stock.picking'].sudo().browse(picking_id)

        if not picking.exists():
            return {"error": "Phiếu không tồn tại."}
        if picking.state not in ['assigned', 'confirmed', 'in_progress']:
            return {"error": f"Phiếu không ở trạng thái cho phép xác nhận (hiện tại: {picking.state})."}
        for move in picking.move_ids_without_package:
            total_done = sum(ml.qty_done for ml in move.move_line_ids)
            if total_done < move.product_uom_qty:
                return {"error": f"⚠️ Sản phẩm '{move.product_id.display_name}' chưa đủ số lượng!"}
        try:
            picking.button_validate()
            return {"success": True, "message": f"✅ Phiếu {picking.name} đã được xác nhận!"}
        except Exception as e:
            return {"error": str(e)}

    @http.route('/pack_scan/check_and_print_label', type='json', auth='user', csrf=False)
    def check_and_print_label(self, **kwargs):
        """
        Kiểm tra picking có package không, nếu có thì trả về URL in nhãn
        """
        picking_id = kwargs.get("picking_id")
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        # Kiểm tra xem có package nào không
        package_ids = picking.move_line_ids.mapped('result_package_id').ids
        has_package = bool(package_ids)
        
        if has_package:
            return {
                "success": True,
                "has_package": True,
                "report_url": f"/report/pdf/hlv_pack_sequence.report_package_label_document/{picking_id}",
                "message": "✅ Đang in nhãn trước khi hoàn thành..."
            }
        else:
            return {
                "success": True,
                "has_package": False,
                "message": "Không có package, tiếp tục hoàn thành"
            }

    # ===================== Fallback: upload 1 phát (nếu cần) =====================
    @http.route('/pack_scan/upload_video', type='http', auth='user', methods=['POST'], csrf=False)
    def upload_pack_video(self, **kwargs):
        httpreq = request.httprequest

        picking_id = httpreq.form.get('picking_id')
        if not picking_id: raise BadRequest("Missing picking_id")
        picking = request.env['stock.picking'].sudo().browse(int(picking_id))
        if not picking.exists(): raise NotFound("Picking not found")

        file = httpreq.files.get('file')
        if not file: raise BadRequest("No file")

        mimetype = (file.mimetype or 'application/octet-stream').split(';', 1)[0]
        if mimetype not in ALLOWED_MIME:
            raise UnsupportedMediaType(f"Unsupported mimetype: {mimetype}")

        data = file.read()
        size_mb = len(data) / 1024 / 1024
        if size_mb > MAX_UPLOAD_MB:
            raise RequestEntityTooLarge(f"File too large: {size_mb:.1f}MB > {MAX_UPLOAD_MB}MB")

        # ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_name = secure_filename(file.filename or f"{picking.name}_PACK.webm").replace('__', '_')
        ext = os.path.splitext(safe_name)[1] or ('.webm' if mimetype == 'video/webm' else '')
        with NamedTemporaryFile(prefix='pack_', suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            # đưa sang background để trả nhanh
            t = threading.Thread(target=_bg_upload_to_drive, args=(request.db, int(picking_id), tmp_path, mimetype), daemon=True)
            t.start()
        except Exception:
            try: os.remove(tmp_path)
            except Exception: pass
            return Response("UPLOAD_FAILED", status=500, content_type='text/plain; charset=utf-8')

        return Response("OK", status=200, content_type='text/plain; charset=utf-8')

    # ===================== Streaming theo CHUNK =====================
    @http.route('/pack_scan/start_upload', type='json', auth='user', csrf=False)
    def start_upload(self, **kw):
        picking_id = int(kw.get('picking_id') or 0)
        ext = (kw.get('ext') or 'webm').strip('.')
        mimetype = kw.get('mimetype') or 'video/webm'
        upload_id = uuid.uuid4().hex
        meta = {
            'picking_id': picking_id,
            'mimetype': mimetype,
            'ext': ext,
            'created': int(time.time()),
            'last_index': -1,
            'path': _file_path(upload_id),
        }
        with open(_meta_path(upload_id), 'w', encoding='utf-8') as f:
            json.dump(meta, f)

        # >>> ADD LOG
        _logger.info("START_UPLOAD id=%s pick=%s path=%s mimetype=%s",
                    upload_id, picking_id, meta['path'], mimetype)

        return {'upload_id': upload_id}


    @http.route('/pack_scan/upload_chunk', type='http', auth='user', methods=['POST'], csrf=False)
    def upload_chunk(self, **kw):
        httpreq = request.httprequest
        upload_id = httpreq.form.get('upload_id') or ''
        index = int(httpreq.form.get('index') or -1)
        file = httpreq.files.get('chunk')
        if not upload_id or index < 0 or not file:
            return Response("bad request", status=400)

        meta_file = _meta_path(upload_id)
        if not os.path.exists(meta_file):
            # >>> ADD LOG
            _logger.warning("UPLOAD_CHUNK no_session id=%s idx=%s", upload_id, index)
            return Response("no session", status=404)

        meta = json.loads(open(meta_file, 'r', encoding='utf-8').read())
        expected = meta.get('last_index', -1) + 1
        if index != expected:
            # >>> ADD LOG
            _logger.warning("UPLOAD_CHUNK out_of_order id=%s idx=%s expected=%s", upload_id, index, expected)
            return Response("out_of_order", status=409)

        chunk = file.read()
        with open(meta['path'], 'ab') as out:
            out.write(chunk)

        meta['last_index'] = index
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f)

        # >>> ADD LOG
        _logger.info("UPLOAD_CHUNK ok id=%s idx=%s size=%s last=%s",
                    upload_id, index, len(chunk), meta['last_index'])

        return Response("OK", status=200, content_type='text/plain')


    @http.route('/pack_scan/finish_upload', type='json', auth='user', csrf=False)
    def finish_upload(self, **kw):
        # Hút param từ nhiều kiểu khác nhau để tránh miss
        params = dict(kw or {})
        if not params and request.httprequest.data:
            try:
                raw = json.loads(request.httprequest.data.decode('utf-8'))
                if isinstance(raw, dict):
                    params = raw.get('params') or raw
            except Exception:
                pass
        if not params:
            params = request.httprequest.form or {}

        upload_id = params.get('upload_id') or params.get('uploadId') or ''
        picking_id = int(params.get('picking_id') or 0)

        # Log để lần sau dễ soi
        _logger.info("FINISH_UPLOAD recv: upload_id=%s picking_id=%s", upload_id, picking_id)

        if not upload_id:
            _logger.warning("FINISH_UPLOAD missing upload_id")
            return {'ok': False, 'msg': 'missing upload_id'}

        meta_file = _meta_path(upload_id)
        if not os.path.exists(meta_file):
            _logger.info("FINISH_UPLOAD already_finished id=%s", upload_id)
            return {'ok': True, 'msg': 'already finished or no session'}

        meta = json.loads(open(meta_file, 'r', encoding='utf-8').read())
        filepath = meta['path']
        mimetype = meta.get('mimetype') or 'video/webm'

        _logger.info("FINISH_UPLOAD id=%s pick=%s file=%s size=%s",
                    upload_id, picking_id, filepath,
                    (os.path.getsize(filepath) if os.path.exists(filepath) else -1))

        t = threading.Thread(target=_bg_upload_to_drive,
                            args=(request.db, picking_id, filepath, mimetype),
                            daemon=True)
        t.start()

        try: os.remove(meta_file)
        except: pass
        return {'ok': True}

      
      
    # ===================== PARTIAL PACK MANAGEMENT =====================
    @http.route('/pack_scan/create_partial_pack', type='json', auth='user', csrf=False)
    def create_partial_pack(self, **kwargs):
        """
        Tạo gói hàng từ các move_line hoàn tất trong picking
        move_line_data: [{'move_line_id': int, 'qty': float}, ...]
        """
        picking_id = kwargs.get("picking_id")
        move_line_data = kwargs.get("move_line_data", [])
        package_barcode = kwargs.get('package_barcode')
        
        _logger.info(f"CREATE_PARTIAL_PACK: picking_id={picking_id}, items={len(move_line_data)}")
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            _logger.error(f"CREATE_PARTIAL_PACK: Picking {picking_id} không tồn tại")
            return {"error": "Phiếu không tồn tại"}
        
        try:
            # Tạo gói hàng (package)
            result = picking.create_partial_pack(move_line_data, package_name=package_barcode)
            _logger.info(f"CREATE_PARTIAL_PACK: Success! New package: {result['package_name']} (ID: {result['package_id']})")
            return {
                "success": True,
                "package_id": result['package_id'],
                "package_name": result['package_name'],
                "message": f"✅ Tạo gói hàng {result['package_name']} thành công!"
            }
        except Exception as e:
            _logger.exception("CREATE_PARTIAL_PACK error")
            return {"error": str(e)}

    @http.route('/pack_scan/unpack', type='json', auth='user', csrf=False)
    def unpack_pack(self, **kwargs):
        """
        Unpack: chuyển items từ partial pack về picking gốc
        """
        picking_id = kwargs.get("picking_id")
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        try:
            picking.unpack_partial()
            return {
                "success": True,
                "message": f"✅ Unpack {picking.name} thành công!"
            }
        except Exception as e:
            _logger.exception("UNPACK error")
            return {"error": str(e)}

    @http.route('/pack_scan/add_to_pack', type='json', auth='user', csrf=False)
    def add_to_pack(self, **kwargs):
        """
        Thêm items vào pack từ picking gốc
        """
        picking_id = kwargs.get("picking_id")
        move_line_data = kwargs.get("move_line_data", [])
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        try:
            picking.add_to_pack(move_line_data)
            return {
                "success": True,
                "message": "✅ Thêm sản phẩm vào pack thành công!"
            }
        except Exception as e:
            _logger.exception("ADD_TO_PACK error")
            return {"error": str(e)}

    @http.route('/pack_scan/transfer_pack_item', type='json', auth='user', csrf=False)
    def transfer_pack_item(self, **kwargs):
        """
        Chuyển items từ pack này sang pack khác
        """
        picking_id = kwargs.get("picking_id")
        target_pack_id = kwargs.get("target_pack_id")
        move_line_data = kwargs.get("move_line_data", [])
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Pack nguồn không tồn tại"}
        
        try:
            picking.transfer_pack_item(target_pack_id, move_line_data)
            return {
                "success": True,
                "message": "✅ Chuyển sản phẩm sang pack khác thành công!"
            }
        except Exception as e:
            _logger.exception("TRANSFER_PACK_ITEM error")
            return {"error": str(e)}

    @http.route('/pack_scan/print_label', type='json', auth='user', csrf=False)
    def print_label(self, **kwargs):
        """
        In nhãn dán cho package
        """
        picking_id = kwargs.get("picking_id")
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        try:
            # Lấy report action
            report_action = request.env.ref(
                'hlv_pack_sequence.action_report_simple_package_labels'
            ).sudo()
            
            return {
                "success": True,
                "report_url": f"/report/pdf/hlv_pack_sequence.report_simple_package_label_document/{picking_id}",
                "message": "✅ Đang chuẩn bị in nhãn..."
            }
        except Exception as e:
            _logger.exception("PRINT_LABEL error")
            return {"error": str(e)}

    @http.route('/pack_scan/print_label_80x80', type='json', auth='user', csrf=False)
    def print_label_80x80(self, **kwargs):
        """
        In nhãn dán cho package format 80x80
        """
        picking_id = kwargs.get("picking_id")
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        try:
            return {
                "success": True,
                "report_url": f"/report/pdf/hlv_pack_sequence.report_package_label_document/{picking_id}",
                "message": "✅ Đang chuẩn bị in nhãn 80x80..."
            }
        except Exception as e:
            _logger.exception("PRINT_LABEL_80X80 error")
            return {"error": str(e)}

    # ===================== PACKAGE EDIT MANAGEMENT =====================
    @http.route('/pack_scan/get_package_details', type='json', auth='user', csrf=False)
    def get_package_details(self, **kwargs):
        """
        Lấy chi tiết sản phẩm trong 1 package để hiển thị modal edit
        """
        picking_id = int(kwargs.get("picking_id") or 0)
        package_id = int(kwargs.get("package_id") or 0)
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        try:
            result = picking.get_package_details(package_id)
            

            
            return result
        except Exception as e:
            _logger.exception("GET_PACKAGE_DETAILS error")
            return {"error": str(e)}

    @http.route('/pack_scan/update_package_item_qty', type='json', auth='user', csrf=False)
    def update_package_item_qty(self, **kwargs):
        """
        Cập nhật số lượng của 1 sản phẩm trong package
        """
        picking_id = kwargs.get("picking_id")
        package_id = kwargs.get("package_id")
        move_line_id = kwargs.get("move_line_id")
        new_qty = kwargs.get("new_qty", 0)
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        try:
            result = picking.update_package_item_qty(package_id, move_line_id, new_qty)
            return result
        except Exception as e:
            _logger.exception("UPDATE_PACKAGE_ITEM_QTY error")
            return {"error": str(e)}

    @http.route('/pack_scan/remove_package_item', type='json', auth='user', csrf=False)
    def remove_package_item(self, **kwargs):
        """
        Xoá 1 sản phẩm khỏi package
        """
        picking_id = kwargs.get("picking_id")
        package_id = kwargs.get("package_id")
        move_line_id = kwargs.get("move_line_id")
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        try:
            result = picking.remove_package_item(package_id, move_line_id)
            return result
        except Exception as e:
            _logger.exception("REMOVE_PACKAGE_ITEM error")
            return {"error": str(e)}

    @http.route('/pack_scan/transfer_item_between_packs', type='json', auth='user', csrf=False)
    def transfer_item_between_packs(self, **kwargs):
        """
        Chuyển 1 sản phẩm từ package này sang package khác
        """
        picking_id = kwargs.get("picking_id")
        source_package_id = kwargs.get("source_package_id")
        target_package_id = kwargs.get("target_package_id")
        move_line_id = kwargs.get("move_line_id")
        qty = kwargs.get("qty", 0)
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        try:
            result = picking.transfer_package_item(source_package_id, target_package_id, move_line_id, qty)
            return result
        except Exception as e:
            _logger.exception("TRANSFER_ITEM_BETWEEN_PACKS error")
            return {"error": str(e)}

    @http.route('/pack_scan/add_item_to_package', type='json', auth='user', csrf=False)
    def add_item_to_package(self, **kwargs):
        """
        Thêm sản phẩm vào package (bổ sung sau)
        """
        picking_id = kwargs.get("picking_id")
        package_id = kwargs.get("package_id")
        move_line_id = kwargs.get("move_line_id")
        qty = kwargs.get("qty", 0)
        
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}
        
        try:
            result = picking.add_item_to_package(package_id, move_line_id, qty)
            return result
        except Exception as e:
            _logger.exception("ADD_ITEM_TO_PACKAGE error")
            return {"error": str(e)}

    @http.route('/pack_scan/split_package', type='json', auth='user', csrf=False)
    def split_package(self, **kwargs):
        """
        Tách 1 package thành phiếu riêng (tạo picking mới và chuyển các move_line)
        """
        picking_id = kwargs.get('picking_id')
        package_id = kwargs.get('package_id')

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            result = picking.split_package_to_new_picking(package_id)
            return {
                'success': True,
                'new_picking_id': result['picking_id'],
                'new_picking_name': result['picking_name'],
                'message': f"✅ Đã tách {result['picking_name']} thành công!"
            }
        except Exception as e:
            _logger.exception('SPLIT_PACKAGE error')
            return {"error": str(e)}

    @http.route('/gdrive/oauth2/disconnect', type='http', auth='user', website=True, csrf=False)
    def disconnect(self, **kw):
        # Xoá token hiện tại => lần sau sẽ bắt đăng nhập lại (chọn tài khoản khác)
        request.env['ir.config_parameter'].sudo().set_param('gdrive.user_credentials_json', '')
        return redirect('/gdrive/oauth2/start')
