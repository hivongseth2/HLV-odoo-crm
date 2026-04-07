/** @odoo-module */
import { ListController } from '@web/views/list/list_controller';
import { patch } from "@web/core/utils/patch";
import { useSetupAction } from "@web/search/action_hook";
import { _t } from "@web/core/l10n/translation";
import { SettingsConfirmationDialog } from "@web/webclient/settings_form_view/settings_confirmation_dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ListConfirmationDialog } from "@web/views/list/list_confirmation_dialog";
import { useExternalListener } from "@odoo/owl";

patch(ListController.prototype, {
/* Patch ListController to restrict auto save in tree views */
   setup(){
      super.setup(...arguments);
      useExternalListener(window, "beforeunload", this.beforeUnload);
      useSetupAction({
          beforeLeave: () => this.beforeLeave(),
//          beforeUnload: (ev) => this.beforeUnload(ev),
      });
   },
   beforeUnload(ev) {
      if(this.model.root.editedRecord){
          ev.preventDefault();
          ev.returnValue = "Unsaved changes";
      }
      if (super.beforeUnload) {
          return super.beforeUnload(ev);
      }
   },
   async beforeLeave() {
   /* function will work before leave the list */
      if(this.model.root.editedRecord){
          if (confirm("Do you want to save changes before leaving?")) {
            return true
          } else {
              this.onClickDiscard();
              return true
          }
      }
   },
});
