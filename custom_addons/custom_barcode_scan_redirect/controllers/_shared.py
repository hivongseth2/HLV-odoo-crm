# -*- coding: utf-8 -*-
"""Shared helpers, constants and background tasks used across controllers."""
from odoo import api, SUPERUSER_ID
from odoo.exceptions import UserError
import logging
import os
import uuid
import json
import tempfile
import time
from datetime import datetime
from markupsafe import Markup, escape

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.client import OAuth2Credentials

_logger = logging.getLogger(__name__)

# ====== Upload config ======
ALLOWED_MIME = {'video/webm', 'video/mp4', 'video/ogg'}
MAX_UPLOAD_MB = 200

# ====== Stream storage for chunked upload ======
# Must survive a worker/container restart (e.g. a production deploy) while a
# recording is still in progress, so this lives under Odoo's persistent
# data_dir (odoo.sh: ~/data, survives builds) instead of the OS tempdir
# (odoo.sh: /tmp, wiped on every new container) which would silently lose
# any in-flight video.
try:
    from odoo.tools import config as _odoo_config
    _data_dir = _odoo_config.get('data_dir')
except Exception:
    _data_dir = None

STREAM_DIR = os.path.join(_data_dir, 'pack_streams') if _data_dir \
    else os.path.join(tempfile.gettempdir(), 'pack_streams')
os.makedirs(STREAM_DIR, exist_ok=True)


def _meta_path(upload_id):
    return os.path.join(STREAM_DIR, f'{upload_id}.meta.json')


def _uploading_meta_path(upload_id):
    return os.path.join(STREAM_DIR, f'{upload_id}.uploading.json')


def _file_path(upload_id):
    return os.path.join(STREAM_DIR, f'{upload_id}.webm')


# ====== Google OAuth settings helpers ======
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


def get_ml_demand(ml):
    """
    Helper lấy số lượng yêu cầu (planned) cho một move_line.
    Khi quét phiếu PICK để vào phiếu PACK, Odoo thường để reserved_qty = 0 ở phiếu PACK.
    Ta phải tìm ngược lại quantity ở dòng tương ứng của phiếu PICK.
    """
    # 1. Ưu tiên lấy từ reservation trực tiếp của dòng (nếu có)
    res = getattr(ml, 'reserved_qty', 0) or getattr(ml, 'reserved_uom_qty', 0) or getattr(ml, 'product_uom_qty', 0) or 0
    if res > 0:
        return res

    # 2. Nếu là dòng có package_id (kiện hàng từ bước trước chuyển sang)
    if ml.package_id:
        orig_mls = ml.move_id.move_orig_ids.mapped('move_line_ids').filtered(
            lambda l: l.result_package_id.id == ml.package_id.id and l.product_id.id == ml.product_id.id
        )
        if orig_mls:
            total = 0.0
            for ol in orig_mls:
                total += getattr(ol, 'quantity', 0) or getattr(ol, 'qty_done', 0) or 0
            return total

    # 3. Fallback: lấy demand từ stock.move (product_uom_qty là demand gốc của move)
    move_demand = ml.move_id.product_uom_qty or 0
    if move_demand > 0:
        n_mls = len(ml.move_id.move_line_ids) or 1
        return move_demand / n_mls

    return 0


def move_package_quants_to_loose(env, package, location=None, logger=None):
    """Move positive quants out of a package using stock.quant APIs."""
    package.ensure_one()
    Quant = env['stock.quant'].sudo()

    domain = [
        ('package_id', '=', package.id),
        ('quantity', '>', 0.0),
    ]
    if location:
        domain.append(('location_id', '=', location.id))

    quants = Quant.search(domain, order='id')
    if not quants:
        return 0.0

    env.cr.execute(
        'SELECT id FROM stock_quant_package WHERE id = %s FOR UPDATE',
        (package.id,),
    )
    env.cr.execute(
        'SELECT id FROM stock_quant WHERE id IN %s ORDER BY id FOR UPDATE',
        [tuple(quants.ids)],
    )
    env.invalidate_all()
    quants = Quant.browse(quants.ids)

    reserved_quants = quants.filtered(lambda q: (q.reserved_quantity or 0.0) > 0.0)
    if reserved_quants:
        raise UserError(
            'Package %s still has reserved quantity; cannot reset package stock safely.'
            % (package.name,)
        )

    moved_qty = 0.0
    for quant in quants:
        qty = quant.quantity or 0.0
        if qty <= 0.0:
            continue

        Quant._update_available_quantity(
            quant.product_id,
            quant.location_id,
            -qty,
            lot_id=quant.lot_id,
            package_id=package,
            owner_id=quant.owner_id,
        )
        Quant._update_available_quantity(
            quant.product_id,
            quant.location_id,
            qty,
            lot_id=quant.lot_id,
            package_id=False,
            owner_id=quant.owner_id,
        )
        moved_qty += qty

    if logger:
        logger.info(
            "Moved %.3f units out of package %s via stock.quant API",
            moved_qty,
            package.name,
        )
    return moved_qty


# ====== Background task: upload file -> Google Drive (My Drive) ======
def _notify_bg_upload_failed(picking, filepath, reason):
    """Post a chatter note when the Drive upload fails, so ops staff know the
    recording wasn't lost and where to look for it (temp file is kept on disk
    on failure instead of being deleted)."""
    if not picking or not picking.exists():
        return
    try:
        body = Markup(
            '⚠️ Upload video đóng gói lên Google Drive THẤT BẠI ({reason}).<br/>'
            'File quay vẫn còn lưu tạm trên server tại: <code>{path}</code><br/>'
            'Vui lòng kiểm tra thư mục tạm (STREAM_DIR) trên server để lấy lại video thủ công.'
        ).format(reason=escape(reason or 'unknown'), path=escape(filepath or ''))
        picking.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
    except Exception:
        _logger.exception("BG_UPLOAD could not post failure note to chatter")


def _bg_upload_to_drive(dbname, picking_id, filepath, mimetype):
    from odoo import registry as odoo_registry
    set_path = None
    success = False
    try:
        with odoo_registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            ICP = env['ir.config_parameter'].sudo()
            picking = env['stock.picking'].sudo().browse(picking_id)

            _logger.info("BG_UPLOAD start db=%s pick=%s file=%s size=%s",
                         dbname, picking_id, filepath,
                         (os.path.getsize(filepath) if os.path.exists(filepath) else -1))

            if not os.path.exists(filepath):
                _logger.warning("BG_UPLOAD skipped missing temp file: %s", filepath)
                _notify_bg_upload_failed(picking, filepath, "không tìm thấy file tạm trên server")
                return

            creds_json = ICP.get_param('gdrive.user_credentials_json') or ''
            if not creds_json:
                _logger.error("BG_UPLOAD missing token")
                _notify_bg_upload_failed(picking, filepath, "chưa kết nối Google Drive (thiếu token)")
                return

            cid   = ICP.get_param('gdrive.oauth_client_id') or ''
            csec  = ICP.get_param('gdrive.oauth_client_secret') or ''
            redir = ICP.get_param('gdrive.oauth_redirect_uri') or ''
            scopes_line = ICP.get_param('gdrive.oauth_scopes') or 'https://www.googleapis.com/auth/drive.file'

            # Lấy warehouse code từ picking
            warehouse_code = picking.location_id.warehouse_id.code or 'DEFAULT'

            # Mapping warehouse code -> folder name
            mapping_str = ICP.get_param('gdrive.warehouse_folder_mapping') or 'TSN:KHO_HCM,KBC:KHO_BENCAM,TSNSR:TSN_SHOWROOM'
            warehouse_mapping = {}
            for item in mapping_str.split(','):
                if ':' in item:
                    code, folder = item.strip().split(':', 1)
                    warehouse_mapping[code.strip()] = folder.strip()

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
                gauth.Authorize()
            except Exception:
                _logger.exception("BG_UPLOAD refresh/authorize failed")
                _notify_bg_upload_failed(picking, filepath, "lỗi xác thực Google Drive (token hết hạn/bị thu hồi)")
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

            if picking.exists():
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
            success = True

    except Exception:
        _logger.exception("BG_UPLOAD fatal")
        try:
            with odoo_registry(dbname).cursor() as cr2:
                env2 = api.Environment(cr2, SUPERUSER_ID, {})
                picking2 = env2['stock.picking'].sudo().browse(picking_id)
                _notify_bg_upload_failed(picking2, filepath, "lỗi không xác định khi upload lên Google Drive")
        except Exception:
            _logger.exception("BG_UPLOAD could not post fatal-failure note to chatter")
    finally:
        if success:
            try: os.remove(filepath)
            except: pass
        else:
            _logger.warning("BG_UPLOAD failed - keeping temp file for manual recovery: %s", filepath)
        if set_path:
            try: os.remove(set_path)
            except: pass
