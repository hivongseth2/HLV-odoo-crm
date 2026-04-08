/** @odoo-module */
import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";
import { useSetupAction } from "@web/search/action_hook";

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        useSetupAction({
            beforeLeave: () => this.beforeLeave(),
        });
    },

    async beforeLeave() {
        const edited = this.model.root.editedRecord;
        if (edited && edited.isDirty) {
            this.onClickDiscard();
        }
    },
});
