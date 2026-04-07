/** @odoo-module */
import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { useSetupAction } from "@web/search/action_hook";
import { _t } from "@web/core/l10n/translation";
import { SettingsConfirmationDialog } from "@web/webclient/settings_form_view/settings_confirmation_dialog";
patch(FormController.prototype, {
/* Patch FormController to restrict auto save in form views */
   setup(){
      super.setup(...arguments);
   },

   async beforeLeave() {
        const dirty = await this.model.root.isDirty();
        if (dirty) {
            return this._confirmSave();
        }
    },

   beforeUnload(ev) {
        // Force commit pending input value before checking dirty state
        const activeEl = document.activeElement;
        if (activeEl && this.rootRef?.el?.contains(activeEl)) {
            activeEl.blur();
        }
        if (this.model.root.dirty) {
            ev.preventDefault();
            ev.returnValue = '';
        }
    },

   beforeVisibilityChange() {
        // Override: do NOT auto-save when tab loses focus / visibility changes.
        // Original Odoo behavior calls this.model.root.save() here,
        // which saves without user confirmation.
    },

   async _confirmSave() {
        let _continue = true;
        await new Promise((resolve) => {
            this.dialogService.add(SettingsConfirmationDialog, {
                body: _t("Would you like to save your changes?"),
                confirm: async () => {
                    await this.save();
                    _continue = true;
                    resolve();
                },
                cancel: async () => {
                    await this.model.root.discard();
                    await this.model.root.save();
                    _continue = true;
                    resolve();
                },
                stayHere: () => {
                    _continue = false;
                    resolve();
                },
            });
        });
        return _continue;
    }
});
