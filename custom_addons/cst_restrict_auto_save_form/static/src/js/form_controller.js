/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { onMounted, onWillUnmount } from "@odoo/owl";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);

        this._onBeforeUnload = (ev) => {
            if (this.model.root.isDirty) {
                ev.preventDefault();
            }
        };

        onMounted(() => {
            window.addEventListener("beforeunload", this._onBeforeUnload);
        });

        onWillUnmount(() => {
            window.removeEventListener("beforeunload", this._onBeforeUnload);
        });
    },

    async beforeLeave() {
        if (this.model.root.isDirty) {
            const canLeave = await this._showUnsavedChangesDialog();
            if (!canLeave) {
                return false;
            }
        }
    },

    _showUnsavedChangesDialog() {
        return new Promise((resolve) => {
            let handled = false;
            this.dialogService.add(
                ConfirmationDialog,
                {
                    title: _t("Thay đổi chưa lưu"),
                    body: _t("Bạn có thay đổi chưa được lưu. Bạn muốn lưu lại không?"),
                    confirmLabel: _t("Lưu"),
                    confirm: async () => {
                        handled = true;
                        await this.model.root.save({
                            noReload: true,
                            stayInEdition: true,
                            useSaveErrorDialog: true,
                        });
                        resolve(true);
                    },
                    cancelLabel: _t("Bỏ thay đổi"),
                    cancel: async () => {
                        handled = true;
                        await this.model.root.discard();
                        resolve(true);
                    },
                },
                {
                    onClose: () => {
                        if (!handled) {
                            resolve(false);
                        }
                    },
                }
            );
        });
    },
});
