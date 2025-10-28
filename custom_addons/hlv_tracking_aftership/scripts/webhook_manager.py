# -*- coding: utf-8 -*-
"""
Script helper để quản lý webhook AfterShip từ Odoo shell (file này có thể xóa)

Cách sử dụng:
1. Mở Odoo shell: python odoo-bin shell -d your_database
2. Import script này: from addons.hlv_tracking_aftership.scripts import webhook_manager
3. Chạy các hàm bên dưới
"""

import logging

_logger = logging.getLogger(__name__)


def register_webhook(env):
    """
    Đăng ký webhook với AfterShip
    
    Usage:
        from addons.hlv_tracking_aftership.scripts import webhook_manager
        webhook_manager.register_webhook(env)
    """
    try:
        # Lấy base URL
        base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
        if not base_url:
            print("❌ Error: 'web.base.url' chưa được cấu hình")
            return False
        
        webhook_url = f"{base_url}/aftership/webhook"
        
        # Tạo client
        api_key = env['ir.config_parameter'].sudo().get_param('aftership.api_key')
        if not api_key:
            print("❌ Error: 'aftership.api_key' chưa được cấu hình")
            return False
        
        from ..services.aftership_client import AfterShipClient
        client = AfterShipClient(api_key)
        
        # Đăng ký webhook
        print(f"📡 Đang đăng ký webhook: {webhook_url}")
        result = client.register_webhook(webhook_url)
        
        # Lưu flag
        env['ir.config_parameter'].sudo().set_param('aftership.webhook_registered', 'true')
        env['ir.config_parameter'].sudo().set_param('aftership.webhook_enabled', 'true')
        
        print(f"✅ Webhook đã được đăng ký thành công!")
        print(f"📋 Response: {result}")
        return True
        
    except Exception as e:
        print(f"❌ Lỗi khi đăng ký webhook: {e}")
        _logger.exception("Failed to register webhook")
        return False


def list_webhooks(env):
    """
    Liệt kê các webhook đã đăng ký
    
    Usage:
        from addons.hlv_tracking_aftership.scripts import webhook_manager
        webhook_manager.list_webhooks(env)
    """
    try:
        api_key = env['ir.config_parameter'].sudo().get_param('aftership.api_key')
        if not api_key:
            print("❌ Error: 'aftership.api_key' chưa được cấu hình")
            return None
        
        from ..services.aftership_client import AfterShipClient
        client = AfterShipClient(api_key)
        
        print("📋 Đang lấy danh sách webhooks...")
        result = client.list_webhooks()
        
        webhooks = result.get('data', {}).get('webhooks', [])
        if webhooks:
            print(f"\n✅ Tìm thấy {len(webhooks)} webhook(s):\n")
            for i, wh in enumerate(webhooks, 1):
                print(f"{i}. ID: {wh.get('id')}")
                print(f"   URL: {wh.get('url')}")
                print(f"   Status: {wh.get('status', 'N/A')}")
                print()
        else:
            print("⚠️  Không có webhook nào được đăng ký")
        
        return webhooks
        
    except Exception as e:
        print(f"❌ Lỗi khi lấy danh sách webhook: {e}")
        _logger.exception("Failed to list webhooks")
        return None


def delete_webhook(env, webhook_id):
    """
    Xóa webhook đã đăng ký
    
    Usage:
        from addons.hlv_tracking_aftership.scripts import webhook_manager
        webhook_manager.delete_webhook(env, 'webhook_id_here')
    """
    try:
        api_key = env['ir.config_parameter'].sudo().get_param('aftership.api_key')
        if not api_key:
            print("❌ Error: 'aftership.api_key' chưa được cấu hình")
            return False
        
        from ..services.aftership_client import AfterShipClient
        client = AfterShipClient(api_key)
        
        print(f"🗑️  Đang xóa webhook: {webhook_id}")
        result = client.delete_webhook(webhook_id)
        
        # Reset flag
        env['ir.config_parameter'].sudo().set_param('aftership.webhook_registered', 'false')
        
        print(f"✅ Webhook đã được xóa thành công!")
        print(f"📋 Response: {result}")
        return True
        
    except Exception as e:
        print(f"❌ Lỗi khi xóa webhook: {e}")
        _logger.exception("Failed to delete webhook")
        return False


def check_webhook_status(env):
    """
    Kiểm tra trạng thái webhook trong Odoo
    
    Usage:
        from addons.hlv_tracking_aftership.scripts import webhook_manager
        webhook_manager.check_webhook_status(env)
    """
    print("\n📊 Trạng thái Webhook trong Odoo:\n")
    
    base_url = env['ir.config_parameter'].sudo().get_param('web.base.url', 'Not set')
    api_key = env['ir.config_parameter'].sudo().get_param('aftership.api_key', 'Not set')
    webhook_enabled = env['ir.config_parameter'].sudo().get_param('aftership.webhook_enabled', 'false')
    webhook_registered = env['ir.config_parameter'].sudo().get_param('aftership.webhook_registered', 'false')
    webhook_secret = env['ir.config_parameter'].sudo().get_param('aftership.webhook_secret', 'Not set')
    
    print(f"1. Base URL: {base_url}")
    print(f"2. API Key: {'✅ Configured' if api_key != 'Not set' else '❌ Not set'}")
    print(f"3. Webhook Enabled: {'✅ Yes' if webhook_enabled == 'true' else '❌ No'}")
    print(f"4. Webhook Registered: {'✅ Yes' if webhook_registered == 'true' else '❌ No'}")
    print(f"5. Webhook Secret: {'✅ Configured' if webhook_secret != 'Not set' else '⚠️  Not set (optional)'}")
    
    if base_url != 'Not set':
        webhook_url = f"{base_url}/aftership/webhook"
        print(f"\n🔗 Webhook URL: {webhook_url}")
    
    print()


def test_webhook_endpoint(env, tracking_number="TEST123"):
    """
    Test webhook endpoint bằng cách tạo payload giả
    
    Usage:
        from addons.hlv_tracking_aftership.scripts import webhook_manager
        webhook_manager.test_webhook_endpoint(env, "JTXXX123")
    """
    print(f"\n🧪 Testing webhook endpoint với tracking_number: {tracking_number}\n")
    
    # Tạo payload giả
    test_payload = {
        "msg": {
            "id": "test_id_123",
            "tracking_number": tracking_number,
            "slug": "jtexpress-vn",
            "tag": "InTransit",
            "subtag": "InTransit_001",
            "status": "InTransit",
            "checkpoints": [
                {
                    "tag": "InTransit",
                    "status": "InTransit",
                    "message": "Đang vận chuyển - TEST",
                    "checkpoint_time": "2025-10-28T10:30:00",
                    "location": "Hà Nội",
                }
            ]
        }
    }
    
    try:
        # Gọi webhook handler trực tiếp
        from ..controllers.webhook import AfterShipWebhook
        controller = AfterShipWebhook()
        
        # Tạo mock request
        class MockRequest:
            jsonrequest = test_payload
            httprequest = type('obj', (object,), {'headers': {}})()
        
        # Inject mock request
        from odoo import http
        old_request = http.request
        http.request = MockRequest()
        
        # Gọi handler
        result = controller.aftership_webhook_handler()
        
        # Restore request
        http.request = old_request
        
        print(f"✅ Webhook test thành công!")
        print(f"📋 Result: {result}")
        
        # Kiểm tra database
        picking = env['stock.picking'].sudo().search([('tracking_number', '=', tracking_number)], limit=1)
        if picking:
            print(f"\n📦 Tìm thấy picking: {picking.name}")
            print(f"   Status: {picking.tracking_status}")
            print(f"   Last Update: {picking.tracking_last_update}")
        
        return True
        
    except Exception as e:
        print(f"❌ Lỗi khi test webhook: {e}")
        _logger.exception("Failed to test webhook")
        return False


def reset_webhook(env):
    """
    Reset tất cả cấu hình webhook
    
    Usage:
        from addons.hlv_tracking_aftership.scripts import webhook_manager
        webhook_manager.reset_webhook(env)
    """
    print("\n🔄 Đang reset cấu hình webhook...\n")
    
    env['ir.config_parameter'].sudo().set_param('aftership.webhook_registered', 'false')
    env['ir.config_parameter'].sudo().set_param('aftership.webhook_enabled', 'false')
    
    print("✅ Đã reset webhook configuration")
    print("   - webhook_registered = false")
    print("   - webhook_enabled = false")
    print("\nBạn có thể đăng ký lại bằng: webhook_manager.register_webhook(env)")


# Hàm tiện ích
def setup_quick(env, api_key=None):
    """
    Setup nhanh webhook
    
    Usage:
        from addons.hlv_tracking_aftership.scripts import webhook_manager
        webhook_manager.setup_quick(env, 'your-api-key')
    """
    print("\n🚀 Quick Setup Webhook\n")
    
    if api_key:
        env['ir.config_parameter'].sudo().set_param('aftership.api_key', api_key)
        print(f"✅ Đã set API key")
    
    # Kiểm tra base_url
    base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
    if not base_url or base_url == 'http://localhost:8069':
        print("⚠️  Warning: web.base.url chưa được set hoặc đang là localhost")
        print("   Webhook sẽ không hoạt động với localhost!")
        new_url = input("   Nhập domain của bạn (ví dụ: https://yourdomain.com): ").strip()
        if new_url:
            env['ir.config_parameter'].sudo().set_param('web.base.url', new_url)
            print(f"✅ Đã set base_url = {new_url}")
    
    # Enable webhook
    env['ir.config_parameter'].sudo().set_param('aftership.webhook_enabled', 'true')
    print("✅ Đã bật webhook")
    
    # Đăng ký
    if api_key or env['ir.config_parameter'].sudo().get_param('aftership.api_key'):
        confirm = input("\nĐăng ký webhook ngay? (y/n): ").strip().lower()
        if confirm == 'y':
            return register_webhook(env)
    else:
        print("\n⚠️  Chưa có API key, không thể đăng ký webhook")
        print("   Chạy lại với: webhook_manager.setup_quick(env, 'your-api-key')")
