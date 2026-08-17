# Paste into the same odoo shell session.
# Checks whether the video for TSN/PACK/12886 actually landed on Google Drive
# even though no chatter note exists (possible if message_post failed AFTER
# a successful Drive upload in the old code).

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.client import OAuth2Credentials
import os, uuid, tempfile

PICKING_NAME = "TSN/PACK/12886"
DATE_FOLDER = "15_08_2026"   # picking was packed 2026-08-15
WAREHOUSE_FOLDER = "KHO_HCM"  # TSN -> KHO_HCM per gdrive.warehouse_folder_mapping

ICP = env['ir.config_parameter'].sudo()
creds_json = ICP.get_param('gdrive.user_credentials_json')
cid = ICP.get_param('gdrive.oauth_client_id')
csec = ICP.get_param('gdrive.oauth_client_secret')
redir = ICP.get_param('gdrive.oauth_redirect_uri')
scopes_line = ICP.get_param('gdrive.oauth_scopes') or 'https://www.googleapis.com/auth/drive.file'

set_path = os.path.join(tempfile.gettempdir(), f'check_{uuid.uuid4().hex}.yaml')
scopes = [s.strip() for s in scopes_line.replace(',', ' ').split() if s.strip()]
with open(set_path, 'w', encoding='utf-8') as f:
    f.write(
        "client_config_backend: settings\n"
        "client_config:\n"
        f"  client_id: \"{cid}\"\n"
        f"  client_secret: \"{csec}\"\n"
        f"  redirect_uri: \"{redir}\"\n"
        "  auth_uri: \"https://accounts.google.com/o/oauth2/v2/auth\"\n"
        "  token_uri: \"https://oauth2.googleapis.com/token\"\n"
        "  revoke_uri: \"https://oauth2.googleapis.com/revoke\"\n"
        "oauth_scope:\n" + "\n".join(f"  - {s}" for s in scopes) + "\n"
        "get_refresh_token: True\n"
        "save_credentials: False\n"
    )

gauth = GoogleAuth(set_path)
gauth.credentials = OAuth2Credentials.from_json(creds_json)
if gauth.access_token_expired:
    gauth.Refresh()
gauth.Authorize()
drive = GoogleDrive(gauth)

def find_folder(name, parent_id=None):
    q = f"mimeType='application/vnd.google-apps.folder' and trashed=false and title='{name}'"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    found = drive.ListFile({'q': q}).GetList()
    return found[0]['id'] if found else None

root_id = find_folder(WAREHOUSE_FOLDER)
print("Warehouse folder", WAREHOUSE_FOLDER, "->", root_id)
day_id = find_folder(DATE_FOLDER, root_id) if root_id else None
print("Date folder", DATE_FOLDER, "->", day_id)
clip_id = find_folder("clip", day_id) if day_id else None
print("clip folder ->", clip_id)

if clip_id:
    files = drive.ListFile({'q': f"'{clip_id}' in parents and trashed=false"}).GetList()
    print(f"\n{len(files)} file(s) in {WAREHOUSE_FOLDER}/{DATE_FOLDER}/clip:")
    for f in files:
        mark = "  <<< possible match" if PICKING_NAME.split('/')[-1] in f['title'] else ""
        print(f"  {f['title']}  ({f.get('alternateLink')}){mark}")
else:
    print("\nCould not reach the clip folder -- either it never got created (no upload ever")
    print("reached that point) or the folder/date naming differs from what's assumed here.")

os.remove(set_path)
