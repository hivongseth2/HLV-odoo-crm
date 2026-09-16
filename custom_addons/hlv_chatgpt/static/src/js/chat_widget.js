/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useExternalListener } from "@odoo/owl";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

export class ChatFormController extends FormController {
    setup() {
        super.setup();
        // FormController không tự gọi onKeydown, phải tự gắn listener.
        // Bắt ở giai đoạn capture để chặn trước khi form xử lý phím Enter.
        useExternalListener(document, "keydown", this.onChatKeydown.bind(this), {
            capture: true,
        });
    }

    onChatKeydown(ev) {
        if (ev.key !== "Enter" || ev.shiftKey || ev.isComposing) {
            return;
        }
        const target = ev.target;
        if (!target || target.tagName !== "TEXTAREA") {
            return;
        }
        const form = target.closest(".o_chat_form");
        const sendBtn = form && form.querySelector(".btn-send-chat");
        if (!sendBtn) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        // blur để Odoo commit nội dung textarea vào record trước khi bấm nút;
        // click ngay lập tức sẽ gửi đi bản thiếu ký tự vừa gõ.
        target.blur();
        setTimeout(() => sendBtn.click());
    }
}

export const chatFormView = { ...formView, Controller: ChatFormController };
registry.category("views").add("hlv_chat_form", chatFormView);
