# wizard/misa_shipping_address_batch_update.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MisaShippingAddressBatchUpdate(models.TransientModel):
    _name = 'misa.shipping.address.batch.update'
    _description = 'Cập nhật địa chỉ giao hàng MISA'

    page = fields.Integer(
        string='Số trang',
        default=1,
        help='Trang hiện tại (mặc định 1). Tăng lên khi chạy lần tiếp theo để tránh fetch lại các đơn đã làm'
    )
    page_size = fields.Integer(
        string='Số lượng/trang',
        default=20,
        help='Số lượng đơn hàng per trang (mặc định 20 cái)'
    )
    dry_run = fields.Boolean(
        string='Chạy thử',
        default=False,
        help='Nếu tích, sẽ xem trước mà không lưu vào database'
    )
    force_update = fields.Boolean(
        string='Cập nhật lại',
        default=False,
        help='Nếu tích, sẽ cập nhật cả những đơn hàng đã có địa chỉ'
    )
    
    # Summary info (readonly)
    total_eligible = fields.Integer(
        string='Tổng cộng đơn chưa giao',
        readonly=True,
        help='Số lượng đơn hàng đủ điều kiện (tên khác S0, state = draft|sale)'
    )
    total_pages = fields.Integer(
        string='Tổng số trang',
        readonly=True,
        help='Tổng số trang cần xử lý'
    )
    status = fields.Text(
        string='Kết quả',
        readonly=True,
        help='Thông tin kết quả xử lý'
    )

    @api.onchange('page_size')
    def _onchange_page_size(self):
        """Tính lại tổng số trang khi thay đổi page_size"""
        if self.page_size > 0:
            self._calculate_summary()

    def action_calculate_summary(self):
        """Tính toán thống kê trước khi chạy"""
        self.ensure_one()
        self._calculate_summary()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'misa.shipping.address.batch.update',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _calculate_summary(self):
        """Tính tổng eligible orders"""
        from ..scripts.update_shipping_address_batch import ShippingAddressUpdater
        
        try:
            misa_utils = self.env['misa.api.utils']
            misa_config = self.env['misa.config']
            crm_token = misa_utils._fetch_login_crm_token()
            misa_headers = misa_config.get_crm_header(crm_token)
            
            updater = ShippingAddressUpdater(self.env, misa_headers)
            
            # Đếm eligible orders
            exclude_with_address = not self.force_update
            self.total_eligible = updater.count_eligible_orders(exclude_with_address=exclude_with_address)
            
            # Tính tổng pages
            import math
            self.total_pages = math.ceil(self.total_eligible / self.page_size) if self.total_eligible > 0 else 0
            
        except Exception as e:
            _logger.error(f"Lỗi tính toán thống kê: {str(e)}", exc_info=True)
            self.total_eligible = 0
            self.total_pages = 0

    @api.model
    def create(self, vals):
        """Tính toán thống kê khi tạo wizard"""
        record = super().create(vals)
        record._calculate_summary()
        return record

    def action_update_shipping_address(self):
        """Main action để cập nhật địa chỉ"""
        self.ensure_one()
        
        try:
            # Import script utilities
            from ..scripts.update_shipping_address_batch import ShippingAddressUpdater
            
            # Get MISA credentials và headers
            misa_utils = self.env['misa.api.utils']
            misa_config = self.env['misa.config']
            
            try:
                crm_token = misa_utils._fetch_login_crm_token()
            except Exception as e:
                raise UserError(_("Lỗi đăng nhập MISA CRM: %s") % str(e))
            
            misa_headers = misa_config.get_crm_header(crm_token)
            
            # Create updater instance
            updater = ShippingAddressUpdater(self.env, misa_headers)
            
            # Run update
            updater.update_sale_orders(
                page=self.page,
                page_size=self.page_size,
                dry_run=self.dry_run,
                force_update=self.force_update
            )
            
            # Build summary
            dry_run_label = " [CHẠY THỬ]" if self.dry_run else ""
            summary = f"""
{dry_run_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THỐNG KÊ KẾT QUẢ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Trang: {self.page}/{self.total_pages}
✅ Cập nhật thành công: {updater.updated_count}
❌ Lỗi: {updater.failed_count}

📋 THÔNG TIN PHÂN TRANG:
   • Tổng đơn chưa giao: {self.total_eligible}
   • Đơn/trang: {self.page_size}
   • Trang hiện tại: {self.page}
   • Trang tiếp theo: {self.page + 1} (nếu cần)

"""
            
            if updater.errors:
                summary += "\n❗ CHI TIẾT LỖI:\n"
                for err in updater.errors[:10]:  # Show max 10 errors
                    summary += f"   • {err['order_name']}: {err['error']}\n"
                if len(updater.errors) > 10:
                    summary += f"   ... và {len(updater.errors) - 10} lỗi khác\n"
            
            summary += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            
            self.status = summary
            
            _logger.info(f"Cập nhật xong: {updater.updated_count} thành công, {updater.failed_count} lỗi")
            
            # Return action để hiển thị kết quả
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'misa.shipping.address.batch.update',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }
            
        except ImportError:
            raise UserError(_("Không tìm thấy script cập nhật. Vui lòng kiểm tra cơ cấu file"))
        except Exception as e:
            _logger.error(f"Lỗi cập nhật: {str(e)}", exc_info=True)
            raise UserError(_("Lỗi cập nhật: %s") % str(e))
