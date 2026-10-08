# -*- coding: utf-8 -*-
"""Hàm thuần cho module hướng dẫn: đặt đường dẫn, mở gói tải lên, chuẩn hoá trang HTML.

Không đụng Odoo (không env, không DB) để test được bằng Python thường.
"""

import html
import io
import re
import unicodedata
import zipfile

INDEX = "index.html"
MAX_FILES = 300
MAX_TOTAL_BYTES = 40 * 1024 * 1024
# File rác do máy nén Mac/Windows thêm vào, không thuộc hướng dẫn.
JUNK_PARTS = ("__MACOSX", ".DS_Store", "Thumbs.db")


def slugify(text):
    """Tên → đoạn đường dẫn: "Hỏi giá NCC" → "hoi-gia-ncc".

    Bỏ dấu tiếng Việt (đ → d), chữ thường, mọi ký tự không phải chữ/số thành một dấu "-",
    bỏ "-" ở hai đầu. None / rỗng / toàn ký tự đặc biệt → "".
    """
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _clean_path(name):
    """Tên file trong zip → đường dẫn tương đối dùng "/". Đường dẫn ra ngoài gói → ValueError."""
    path = name.replace("\\", "/")
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if path.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
        raise ValueError(f"Đường dẫn không hợp lệ trong file nén: {name}")
    return "/".join(parts)


def _read_zip(data):
    """bytes zip → {đường dẫn: bytes} (chưa bỏ thư mục gốc). Hỏng / quá giới hạn → ValueError."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("File nén bị hỏng, không mở được.") from exc
    infos = [
        info for info in archive.infolist()
        if not info.is_dir() and not any(junk in info.filename for junk in JUNK_PARTS)
    ]
    if len(infos) > MAX_FILES:
        raise ValueError(f"File nén có {len(infos)} file, tối đa {MAX_FILES}.")
    # Xét kích thước sau giải nén TRƯỚC khi đọc — zip vài KB có thể bung ra hàng GB.
    if sum(info.file_size for info in infos) > MAX_TOTAL_BYTES:
        raise ValueError(f"Nội dung giải nén vượt {MAX_TOTAL_BYTES // (1024 * 1024)}MB.")
    return {_clean_path(info.filename): archive.read(info) for info in infos}


def _strip_common_root(files):
    """Mọi file cùng nằm trong một thư mục (nén cả thư mục) → bỏ thư mục đó đi."""
    roots = {path.split("/", 1)[0] for path in files}
    if len(roots) == 1 and all("/" in path for path in files):
        return {path.split("/", 1)[1]: content for path, content in files.items()}
    return files


def unpack_package(data):
    """Gói tải lên → {đường dẫn tương đối: bytes}, luôn có "index.html".

    data: bytes của một file .html, hoặc .zip chứa trang + ảnh/CSS đi kèm (đường dẫn trong
    trang là tương đối, VD img/a.png). Nén cả thư mục thì thư mục gốc được bỏ. Zip chỉ có
    đúng một file .html ở gốc mà không tên index.html thì đổi tên thành index.html.
    Rỗng, không phải HTML/zip, zip hỏng, đường dẫn ra ngoài gói, quá MAX_FILES file hoặc
    MAX_TOTAL_BYTES, không tìm ra trang chính → ValueError (thông điệp cho người dùng).
    """
    if not data:
        raise ValueError("Chưa chọn file.")
    if data[:4] == b"PK\x03\x04":
        files = _strip_common_root(_read_zip(data))
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Chỉ nhận file .html (UTF-8) hoặc .zip.") from exc
        if "<" not in text[:2000]:
            raise ValueError("File không phải trang HTML.")
        return {INDEX: data}
    if INDEX not in files:
        pages = [path for path in files if "/" not in path and path.lower().endswith((".html", ".htm"))]
        if len(pages) != 1:
            raise ValueError("File nén phải có index.html (hoặc đúng một file .html) ở thư mục gốc.")
        files[INDEX] = files.pop(pages[0])
    return files


def normalize_document(page):
    """Bảo đảm trang bắt đầu bằng <!doctype html> và khai UTF-8.

    Trang xuất từ Artifact đôi khi chỉ là một đoạn (<title>, <style>, nội dung) — thiếu
    doctype thì trình duyệt chạy chế độ quirks và vỡ bố cục, thiếu charset thì lỗi dấu tiếng
    Việt. page: str. Đã có doctype → trả nguyên; chưa có → thêm doctype + charset + viewport.
    """
    if page.lstrip().lower().startswith("<!doctype"):
        return page
    return (
        '<!doctype html>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n' + page
    )


def add_back_link(page, href, label):
    """Chèn nút nổi "← label" ở góc dưới trái để quay về danh sách hướng dẫn.

    Nút nổi (position: fixed) thay vì thanh trên cùng để không đẩy lệch bố cục của trang
    hướng dẫn. page: str; href, label: str (được escape). Có </body> → chèn ngay trước nó,
    không có → thêm vào cuối trang.
    """
    link = (
        f'<a href="{html.escape(href)}" style="position:fixed;left:12px;bottom:12px;z-index:2147483647;'
        "padding:7px 14px;border-radius:999px;background:#1c1c1a;color:#fff;"
        "font:600 13px/1.3 system-ui,-apple-system,'Segoe UI',sans-serif;text-decoration:none;"
        f'box-shadow:0 2px 10px rgba(0,0,0,.25)">← {html.escape(label)}</a>'
    )
    match = re.search(r"</body\s*>", page, flags=re.IGNORECASE)
    if not match:
        return page + link
    return page[:match.start()] + link + page[match.start():]
