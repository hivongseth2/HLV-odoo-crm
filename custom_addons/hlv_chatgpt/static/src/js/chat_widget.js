/** @odoo-module **/
import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

export class ChatFormController extends FormController {
    setup() {
        super.setup();
    }

    /**
     * Ghi đè hàm onSaved hoặc thêm sự kiện lắng nghe
     * Tuy nhiên, cách đơn giản nhất trong Odoo 16/17/18 là can thiệp vào onRender
     * hoặc bind sự kiện trực tiếp lên field.
     */
    
    // Xử lý sự kiện phím bấm trên toàn bộ Form này
    onKeydown(ev) {
        // Nếu đang focus vào ô nhập liệu có name="input_text"
        if (ev.target.name === "input_text" || ev.target.getAttribute("name") === "input_text") {
            if (ev.key === "Enter" && !ev.shiftKey) {
                ev.preventDefault(); // Chặn xuống dòng
                ev.stopPropagation();
                
                // Tìm nút Gửi và click
                const sendBtn = this.root.el.querySelector('button[name="action_send_message"]');
                if (sendBtn) {
                    sendBtn.click();
                }
            }
        }
    }
}

// Kế thừa Form View để gắn Controller mới vào
export const chatFormView = {
    ...formView,
    Controller: ChatFormController,
};

// Đăng ký view mới vào registry với tên 'hlv_chat_form'
registry.category("views").add("hlv_chat_form", chatFormView);