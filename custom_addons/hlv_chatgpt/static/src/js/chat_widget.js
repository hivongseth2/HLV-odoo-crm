/** @odoo-module **/
import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

export class ChatFormController extends FormController {
    setup() {
        super.setup();
        console.log("HLV Chat Widget: Controller Loaded!"); // Log để kiểm tra JS đã chạy chưa
    }

    /**
     * Bắt sự kiện phím bấm trên toàn bộ Form View
     */
    onKeydown(ev) {
        // Kiểm tra nếu phím nhấn là Enter (và không giữ Shift)
        if (ev.key === "Enter" && !ev.shiftKey) {

            // Logic mới: Kiểm tra nếu đang focus vào ô Textarea bất kỳ trong view này
            if (ev.target.tagName === "TEXTAREA") {
                console.log("HLV Chat Widget: Enter detected!");

                ev.preventDefault(); // Chặn xuống dòng
                ev.stopPropagation(); // Chặn sự kiện lan truyền

                // Tìm nút Gửi (class .btn-send-chat) và click
                const sendBtn = this.root.el.querySelector('.btn-send-chat');
                if (sendBtn) {
                    sendBtn.click();
                } else {
                    console.warn("HLV Chat Widget: Send button not found!");
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