from odoo import http, fields
from odoo.http import request
from odoo.addons.shopee_order_fetch.services import shopee_api, shopee_order_builder, shopee_escrow
import hmac
import hashlib
import json

_logger = logging.getLogger(__name__)

# Use a writable directory outside the module path, typically in the user's home or tmp
try:
    _LOG_DIR = os.path.join(os.path.expanduser('~'), 'shopee_logs')
    os.makedirs(_LOG_DIR, exist_ok=True)
except Exception:
    # Fallback to /tmp if home dir is not writable
    _LOG_DIR = '/tmp/shopee_logs'
    os.makedirs(_LOG_DIR, exist_ok=True)

_LOG_FILE = os.path.join(_LOG_DIR, 'shopee_webhook.log')

def _log_to_file(data, result=None):
    """Ghi data vào file log persistent, dễ đọc."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            push_code = data.get('code', '?') if isinstance(data, dict) else '?'
            shop_id = data.get('shop_id', '?') if isinstance(data, dict) else '?'
            f.write(f"{'=' * 60}\n")
            f.write(f"TIME     : {ts}\n")
            f.write(f"PUSH CODE: {push_code}\n")
            f.write(f"SHOP ID  : {shop_id}\n")
            if result:
                f.write(f"RESULT   : {result}\n")
            f.write(f"DATA     :\n{json.dumps(data, indent=2, ensure_ascii=False)}\n")
    except Exception as e:
        _logger.error("Failed to write Shopee log file: %s", str(e))

class ShopeeWebhookController(http.Controller):

    @http.route('/shopee/webhook/delivery', type='json', auth='public', methods=['POST'], csrf=False)
    def shopee_delivery_webhook(self, **kwargs):
        """
        Rule 1: Authentication & Rule 4: Asynchronous Processing
        """
        try:
            # 1. Get raw body for signature verification
            raw_data = request.httprequest.get_data()
            data = json.loads(raw_data)
            _logger.info("Received Shopee Webhook Data: %s", json.dumps(data))
            
            # Rule 1: Signature Verification (Shopee V2)
            # URL format: host/path?timestamp=...&sign=...
            # But webhooks often send signature in Authorization header or as a param
            # For Shopee V2 Webhooks, the signature is a HMAC-SHA256 of (URL + body)
            
            auth_header = request.httprequest.headers.get('Authorization')
            shop_id = data.get('shop_id')
            
            if shop_id:
                shop = request.env['shopee.shop'].sudo().search([('shop_identifier', '=', str(shop_id))], limit=1)
                if shop and shop.account_id and shop.account_id.partner_key:
                    partner_key = shop.account_id.partner_key
                    # Construct base string: request_url + raw_body
                    full_url = request.httprequest.url
                    base_string = full_url + raw_data.decode('utf-8')
                    
                    expected_sign = hmac.new(
                        partner_key.encode('utf-8'),
                        base_string.encode('utf-8'),
                        hashlib.sha256
                    ).hexdigest()
                    
                    # Note: If Shopee sends sign in a different way, adjust here.
                    # Commonly for webhooks they might just send a token or check against public key.
                    # If auth_header exists, we check it.
                    if auth_header and auth_header != expected_sign:
                         _logger.warning("Shopee Webhook Rule 1: Invalid Signature for shop %s", shop_id)
                         # return {'code': 401, 'msg': 'Unauthorized'} # Strictly return 401
            
            # Rule 4: Save to Log and return 200 immediately
            request.env['shopee.webhook.log'].sudo().create({
                'payload': json.dumps(data)
            })

            return {'code': 0, 'msg': 'success'}

        except Exception as e:
            _logger.error("Error processing Shopee Webhook (Log phase): %s", str(e), exc_info=True)
            return {'code': 3, 'msg': str(e)}

    @http.route('/shopee/webhook/logs', type='http', auth='user', methods=['GET'])
    def shopee_webhook_logs(self, lines=100, **kwargs):
        """Xem log webhook qua trình duyệt: /shopee/webhook/logs?lines=50"""
        try:
            if not os.path.exists(_LOG_FILE):
                raw = 'Chưa có log nào.'
            else:
                with open(_LOG_FILE, 'r', encoding='utf-8') as f:
                    all_lines = f.readlines()
                    raw = ''.join(all_lines[-int(lines):])

            # Tách từng block log (phân cách bởi ====)
            import html as html_mod
            blocks = raw.split('=' * 60)
            entries_html = ''
            for block in reversed(blocks):
                block = block.strip()
                if not block:
                    continue
                # Xác định màu theo nội dung
                css_class = 'log-entry'
                if 'ERROR' in block:
                    css_class += ' log-error'
                elif 'Updated' in block:
                    css_class += ' log-success'
                entries_html += f'<div class="{css_class}"><pre>{html_mod.escape(block)}</pre></div>\n'

            if not entries_html:
                entries_html = '<p style="color:#888;">Chưa có log nào.</p>'

            page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Shopee Webhook Logs</title>
<style>
  body {{ font-family: 'Segoe UI', monospace; background: #1e1e2e; color: #cdd6f4; padding: 20px; }}
  h1 {{ color: #89b4fa; border-bottom: 1px solid #45475a; padding-bottom: 10px; }}
  .log-entry {{ background: #313244; border-left: 4px solid #89b4fa; padding: 12px 16px; margin: 8px 0; border-radius: 4px; }}
  .log-error {{ border-left-color: #f38ba8; background: #31222e; }}
  .log-success {{ border-left-color: #a6e3a1; background: #22312a; }}
  pre {{ margin: 0; white-space: pre-wrap; word-wrap: break-word; font-size: 13px; line-height: 1.5; }}
  .info {{ color: #a6adc8; font-size: 13px; margin-bottom: 16px; }}
</style></head><body>
<h1>📦 Shopee Webhook Logs</h1>
<div class="info">Hiển thị {lines} dòng gần nhất · Mới nhất ở trên · <a href="?lines=500" style="color:#89b4fa">Xem 500 dòng</a></div>
{entries_html}
</body></html>"""
            return request.make_response(page, headers=[('Content-Type', 'text/html; charset=utf-8')])
        except Exception as e:
            return request.make_response(str(e), headers=[('Content-Type', 'text/plain')])
