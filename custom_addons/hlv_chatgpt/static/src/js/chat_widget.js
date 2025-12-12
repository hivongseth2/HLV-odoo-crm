/** @odoo-module **/
import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { useSetupAction } from "@web/search/action_hook";

export class ChatFormController extends FormController {
    setup() {
        super.setup();
    }

    /**
     * Bắt sự kiện phím bấm trên toàn bộ Form View
     */
    onKeydown(ev) {
        // Kiểm tra nếu phím nhấn là Enter (và không giữ Shift)
        if (ev.key === "Enter" && !ev.shiftKey) {
            // Kiểm tra xem người dùng có đang gõ trong ô nhập liệu chat không
            // Chúng ta sẽ thêm class 'chat-input-field' cho field này trong XML
            if (ev.target.closest('.chat-input-field')) {
                ev.preventDefault(); // Chặn xuống dòng mặc định
                ev.stopPropagation();

                // Tìm nút Gửi và kích hoạt click
                const sendBtn = this.root.el.querySelector('.btn-send-chat');
                if (sendBtn) {
                    sendBtn.click();
                }
            }
        }
    }
}

// Định nghĩa View mới sử dụng Controller ở trên
export const chatFormView = {
    ...formView,
    Controller: ChatFormController,
};

// Đăng ký vào hệ thống
registry.category("views").add("hlv_chat_form", chatFormView);