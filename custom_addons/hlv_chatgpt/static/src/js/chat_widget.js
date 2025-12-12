/** @odoo-module **/
import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

export class ChatFormController extends FormController {
    setup() { super.setup(); }
    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            if (ev.target.tagName === "TEXTAREA") {
                ev.preventDefault(); ev.stopPropagation();
                const sendBtn = this.root.el.querySelector('.btn-send-chat');
                if (sendBtn) sendBtn.click();
            }
        }
    }
}
export const chatFormView = { ...formView, Controller: ChatFormController };
registry.category("views").add("hlv_chat_form", chatFormView);