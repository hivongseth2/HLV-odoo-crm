/** @odoo-module */
import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { onMounted } from "@odoo/owl";

patch(FormController.prototype, {

    setup() {
        super.setup(...arguments);
        this._formInDialog = false;
        this._leaveDecisionMade = false;
        onMounted(() => {
            this._formInDialog = !!this.rootRef?.el?.closest(".o_dialog");
        });
    },

    async beforeLeave() {
        if (this._formInDialog) {
            return;
        }
        if (this._leaveDecisionMade) {
            this._leaveDecisionMade = false;
            return;
        }
        if (this.model.root.isDirty) {
            return this._confirmSave();
        }
    },

    beforeUnload(ev) {
        if (this._formInDialog) {
            return;
        }
        if (this.model.root.isDirty) {
            ev.preventDefault();
            ev.returnValue = "";
        }
    },

    beforeVisibilityChange() {
        // do NOT auto-save when tab loses focus
    },

    async _confirmSave() {
        let _continue = true;
        await new Promise((resolve) => {
            let handled = false;
            this.dialogService.add(
                ConfirmationDialog,
                {
                    title: _t("Thay đổi chưa được lưu"),
                    body: _t("Bạn có muốn lưu các thay đổi của mình không?"),
                    confirmLabel: _t("Lưu"),
                    confirm: async () => {
                        handled = true;
                        this._leaveDecisionMade = true;
                        await this.save();
                        _continue = true;
                        resolve();
                    },
                    cancelLabel: _t("Huỷ bỏ"),
                    cancel: async () => {
                        handled = true;
                        this._leaveDecisionMade = true;
                        await this.model.root.discard();
                        _continue = true;
                        resolve();
                    },
                },
                {
                    onClose: () => {
                        if (!handled) {
                            _continue = false;
                            resolve();
                        }
                    },
                }
            );
        });
        return _continue;
    },
});
