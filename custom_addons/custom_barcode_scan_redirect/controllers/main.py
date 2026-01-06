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

        # Lấy danh sách packages của picking hiện tại
        picking_packages = []
        MoveLine = request.env['stock.move.line']
        package_ids = picking.move_line_ids.mapped('result_package_id').ids
        if package_ids:
            packages = request.env['stock.quant.package'].sudo().browse(package_ids)
            picking_packages = [{
                'id': pkg.id,
                'name': pkg.name,
                'qty': sum(ml.qty_done for ml in picking.move_line_ids.filtered(lambda ml: ml.result_package_id.id == pkg.id)),
                'package_lines': [{
                    'product_name': ml.product_id.display_name,
                    'product_qty': ml.qty_done,
                    'product_uom': ml.product_uom_id.name,
                } for ml in picking.move_line_ids.filtered(lambda ml: ml.result_package_id.id == pkg.id)],
            } for pkg in packages]

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
        _logger = logging.getLogger(__name__)
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        # Tìm move dựa trên barcode
        moves = picking.move_ids_without_package.filtered(lambda m: m.product_id.barcode == barcode)
        if not moves:
            return {"error": "❌ Mã sản phẩm không khớp trong phiếu!"}
        # Tính tổng quát để check xem đã đủ hết chưa
        total_required = sum(m.product_uom_qty for m in moves)
        total_done = sum(sum(ml.qty_done for ml in m.move_line_ids) for m in moves)
        if delta > 0 and total_done >= total_required:
            return {"error": "⚠️ Sản phẩm này đã được quét đủ!"}
        updated_lines = []
        
        # --- LOGIC MỚI: Xử lý tìm line_id tự động nếu FE gửi lên null ---
        target_ml = None
        
        # Nếu có line_id cụ thể từ FE
        if line_id:
            target_ml = request.env['stock.move.line'].sudo().browse(int(line_id))
            if not target_ml.exists():
                target_ml = None # Fallback nếu ID sai
        # Nếu chưa xác định được target_ml (do line_id null hoặc sai), tự động tìm dòng phù hợp
        if not target_ml:
            for move in moves:
                for ml in move.move_line_ids:
                    # Nếu đang cộng: tìm dòng chưa đủ
                    if delta > 0:
                        if ml.qty_done < move.product_uom_qty: # (logic đơn giản, có thể chỉnh theo demand của line)
                            # So sánh với reserved hoặc logic phân bổ của bạn. 
                            # Ở đây giả định muốn fill vào dòng chưa full
                            remaining = move.product_uom_qty - sum(l.qty_done for l in move.move_line_ids)
                            if remaining > 0:
                                target_ml = ml
                                break
                    # Nếu đang trừ: tìm dòng có qty_done > 0
                    elif delta < 0:
                        if ml.qty_done > 0:
                            # [VALIDATION] Check if line is already packed
                            if ml.result_package_id:
                                # Nếu đã đóng gói -> Bỏ qua dòng này (uu tiên dòng chưa đóng gói trước)
                                # Nhưng nếu chỉ còn dòng này? Chúng ta sẽ check lại ở dưới.
                                continue 
                            target_ml = ml
                            break
                if target_ml:
                    break
        
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
            move_total_done = sum(l.qty_done for l in move.move_line_ids)
            move_remain = max(0, move.product_uom_qty - move_total_done)
            if delta > 0:
                # Chỉ cộng phần còn thiếu của move này
                add_qty = min(delta, move_remain) if delta > 0 else 0.0
                
                if add_qty > 0:
                    new_qty = current_qty + add_qty
                    ml.write({'qty_done': new_qty})
                    
                    # Tính lại tổng done để trả về FE
                    new_total_done = move_total_done - current_qty + new_qty
                    
                    updated_lines.append({
                        "line_id": ml.id,
                        "product": move.product_id.display_name,
                        "done_qty": new_total_done,
                        "required_qty": move.product_uom_qty,
                        "barcode": move.product_id.barcode # Trả về barcode để FE map lại nếu cần
                    })
            
            elif delta < 0:
                reduce_qty = min(abs(delta), current_qty)
                if reduce_qty > 0:
                    new_qty = current_qty - reduce_qty
                    ml.write({'qty_done': new_qty})
                    
                    new_total_done = move_total_done - current_qty + new_qty
                    
                    updated_lines.append({
                        "line_id": ml.id,
                        "product": move.product_id.display_name,
                        "done_qty": new_total_done,
                        "required_qty": move.product_uom_qty,
                        "barcode": move.product_id.barcode
                    })
        if not updated_lines:
            # Trường hợp delta > 0 nhưng không tìm thấy dòng nào còn thiếu (dù check tổng ở trên đã pass)
            # Có thể do logic phân bổ move_line phức tạp, ta báo lỗi hoặc ignore
            return {"error": "⚠️ Không tìm thấy dòng sản phẩm phù hợp để cập nhật! Có thể sản phẩm đã "}
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

    # ===================== PACKAGE EDIT MANAGEMENT =====================
    @http.route('/pack_scan/get_package_details', type='json', auth='user', csrf=False)
    def get_package_details(self, **kwargs):
        """
        Lấy chi tiết sản phẩm trong 1 package để hiển thị modal edit
        """
        picking_id = kwargs.get("picking_id")
        package_id = kwargs.get("package_id")
        
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
