/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { SettingsConfirmationDialog } from "@web/webclient/settings_form_view/settings_confirmation_dialog";

patch(FormController.prototype, {

    setup() {
        super.setup(...arguments);
        this._stayOnForm = false;
    },

    async beforeLeave() {
        if (this._stayOnForm) {
            return false; // stay on form (default Odoo behavior)
        }

        if (await this.model.root.isDirty()) {
            return await this._confirmSave();
        }
        return true;
    },

    async onPagerUpdate({ offset, resIds }) {
        if (await this.model.root.isDirty()) {
            const confirmed = await this._confirmSave();
            if (!confirmed) {
                return false;
            }
        }
        return this.model.load({ resId: resIds[offset] });
    },

    async _confirmSave() {
        return new Promise((resolve) => {
            this.dialogService.add(SettingsConfirmationDialog, {
                body: _t("Would you like to save your changes?"),
                confirm: async () => {
                    this._stayOnForm = true;
                    await this.save();
                    this._stayOnForm = false;
                    resolve(false); // prevent leaving current record
                },

                cancel: async () => {
                    this._stayOnForm = true;
                    await this.model.root.discard();
                    this._stayOnForm = false;
                    resolve(false);
                },

                stayHere: () => {
                    resolve(false);
                },
            });
        });
    },
});
