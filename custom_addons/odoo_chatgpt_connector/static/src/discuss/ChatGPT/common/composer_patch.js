/** @odoo-module **/
import { Composer } from "@mail/core/common/composer";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { ChatGPTPromptDialog } from "@html_editor/main/chatgpt/chatgpt_prompt_dialog";

patch(Composer.prototype, {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
    },
    onClickGPT() {
        this.dialogService.add(ChatGPTPromptDialog, {
            insert: (content) => this.props.composer.text += ` ${content.textContent}`,
            sanitize: (fragment) => DOMPurify.sanitize(fragment, {
                IN_PLACE: true, ADD_TAGS: ["#document-fragment"], ADD_ATTR: ["contenteditable"],
            }),
        });
    },
});
