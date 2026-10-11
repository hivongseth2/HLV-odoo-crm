# -*- coding: utf-8 -*-
"""Đọc file .doc (Word 97-2003, nhị phân) thành blocks, không cần thư viện ngoài.

Làm đúng ba việc: đọc container OLE2 để lấy luồng WordDocument và Table; đọc piece table
để ghép đúng thứ tự văn bản; đổi dấu field (0x13/0x14/0x15) thành trường MERGEFIELD.

Giới hạn cố ý (ghi rõ để người dùng kiểm lại sau khi import):
- Không đọc định dạng ký tự/đoạn (đậm, nghiêng, căn lề) -> chỉ còn chữ và trường trộn.
- Bảng: 0x07 là dấu kết thúc ô, hai 0x07 liền nhau là kết thúc dòng. Ô trống ngay
  sau một ô khác có thể bị hiểu nhầm là kết thúc dòng; cần kiểm tra bảng sau import.
- Chỉ lấy phần thân văn bản (ccpText), bỏ đầu/chân trang và chú thích.
Đầu vào: bytes của file .doc. Đầu ra: blocks (xem docx_io). Lỗi cấu trúc -> ValueError.
"""

import struct

from .docx_io import clean_runs, merge_field_name

_OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
_FREE = 0xFFFFFFFF
_END_OF_CHAIN = 0xFFFFFFFE
_MAX_CHAIN = 1000000
_MINI_CUTOFF = 4096
_TYPE_STREAM = 2
_TYPE_ROOT = 5


class _Ole:
    """Container OLE2 chỉ đọc."""

    def __init__(self, data):
        if data[:8] != _OLE_MAGIC:
            raise ValueError('File không phải .doc nhị phân (thiếu chữ ký OLE2)')
        self.data = data
        self.sector_size = 1 << struct.unpack_from('<H', data, 0x1E)[0]
        self.mini_size = 1 << struct.unpack_from('<H', data, 0x20)[0]
        num_fat, first_dir = struct.unpack_from('<II', data, 0x2C)
        first_mini_fat, num_mini_fat, first_difat, num_difat = struct.unpack_from('<IIII', data, 0x3C)
        self.fat = self._load_fat(num_fat, first_difat, num_difat, data)
        self.directory = self._read_directory(first_dir)
        root = next((e for e in self.directory if e['type'] == _TYPE_ROOT), None)
        # Luồng ministream của root luôn nằm trên sector thường, không qua mini FAT
        self.mini_stream = self._read_chain_raw(root['start'], root['size']) if root else b''
        self.mini_fat = self._unpack_table(self._read_chain_raw(first_mini_fat, num_mini_fat * self.sector_size))

    def _sector(self, sid):
        offset = (sid + 1) * self.sector_size
        if offset + self.sector_size > len(self.data):
            raise ValueError('File .doc bị cắt cụt (sector %d nằm ngoài file)' % sid)
        return self.data[offset:offset + self.sector_size]

    def _unpack_table(self, raw):
        count = len(raw) // 4
        return list(struct.unpack('<%dI' % count, raw[:count * 4]))

    def _load_fat(self, num_fat, first_difat, num_difat, data):
        difat = [s for s in struct.unpack_from('<109I', data, 0x4C) if s != _FREE][:num_fat]
        sid = first_difat
        loops = 0
        while len(difat) < num_fat and sid not in (_END_OF_CHAIN, _FREE) and loops < num_difat + 1:
            entries = self._unpack_table(self._sector(sid))
            difat += [s for s in entries[:-1] if s != _FREE]
            sid = entries[-1]
            loops += 1
        fat = []
        for fat_sid in difat[:num_fat]:
            fat += self._unpack_table(self._sector(fat_sid))
        return fat

    def _chain_ids(self, start, table):
        ids = []
        sid = start
        while sid < _END_OF_CHAIN and len(ids) < _MAX_CHAIN:
            ids.append(sid)
            if sid >= len(table):
                raise ValueError('Chuỗi sector của .doc trỏ ra ngoài FAT')
            sid = table[sid]
        return ids

    def _read_chain_raw(self, start, size):
        chunks = [self._sector(s) for s in self._chain_ids(start, self.fat)]
        return b''.join(chunks)[:size]

    def _read_chain(self, start, size):
        if size < _MINI_CUTOFF:
            return self._read_mini_chain(start, size)
        return self._read_chain_raw(start, size)

    def _read_mini_chain(self, start, size):
        parts = []
        for sid in self._chain_ids(start, self.mini_fat):
            parts.append(self.mini_stream[sid * self.mini_size:(sid + 1) * self.mini_size])
        return b''.join(parts)[:size]

    def _read_directory(self, first_dir):
        raw = b''.join(self._sector(s) for s in self._chain_ids(first_dir, self.fat))
        entries = []
        for off in range(0, len(raw) - 127, 128):
            entry = raw[off:off + 128]
            name_len = struct.unpack_from('<H', entry, 64)[0]
            name = entry[:max(name_len - 2, 0)].decode('utf-16le', errors='ignore')
            entries.append({
                'name': name,
                'type': entry[66],
                'start': struct.unpack_from('<I', entry, 116)[0],
                'size': struct.unpack_from('<I', entry, 120)[0],
            })
        return entries

    def stream(self, name):
        entry = next((e for e in self.directory if e['type'] == _TYPE_STREAM and e['name'] == name), None)
        if entry is None:
            return None
        return self._read_chain(entry['start'], entry['size'])


def _piece_text(word, table_stream):
    """Ghép toàn bộ văn bản theo piece table (Clx) trong table_stream."""
    fc_clx, lcb_clx = struct.unpack_from('<II', word, 0x1A2)
    clx = table_stream[fc_clx:fc_clx + lcb_clx]
    pos = 0
    while pos < len(clx) and clx[pos] == 0x01:
        pos += 3 + struct.unpack_from('<H', clx, pos + 1)[0]
    if pos >= len(clx) or clx[pos] != 0x02:
        raise ValueError('Không tìm thấy piece table trong .doc')
    lcb = struct.unpack_from('<I', clx, pos + 1)[0]
    plc = clx[pos + 5:pos + 5 + lcb]
    count = (len(plc) - 4) // 12
    cps = struct.unpack_from('<%dI' % (count + 1), plc, 0)
    out = []
    for idx in range(count):
        fc = struct.unpack_from('<I', plc, 4 * (count + 1) + idx * 8 + 2)[0]
        chars = cps[idx + 1] - cps[idx]
        if fc & 0x40000000:
            offset = (fc & 0x3FFFFFFF) // 2
            out.append(word[offset:offset + chars].decode('cp1252', errors='replace'))
        else:
            offset = fc & 0x3FFFFFFF
            out.append(word[offset:offset + chars * 2].decode('utf-16le', errors='replace'))
    return ''.join(out)


class _BlockBuilder:
    """Duyệt từng ký tự của văn bản và dựng blocks (đoạn và bảng)."""

    def __init__(self):
        self.blocks = []
        self.runs = []
        self.cell_paras = []
        self.row_cells = []
        self.table_rows = None
        self.stack = []
        self.prev = ''

    def _paragraph(self):
        return {'type': 'p', 'align': 'left', 'runs': clean_runs(self.runs)}

    def _close_table(self):
        if self.table_rows is not None:
            self.blocks.append({'type': 'table', 'rows': self.table_rows})
            self.table_rows = None

    def _field_begin(self):
        self.stack.append({'instr': '', 'stage': 'instr', 'merge': False})

    def _field_separate(self):
        top = self.stack[-1]
        top['stage'] = 'result'
        name = merge_field_name(top['instr'])
        if name:
            top['merge'] = True
            self.runs.append({'field': name})

    def _field_end(self):
        top = self.stack.pop()
        name = merge_field_name(top['instr'])
        if top['stage'] == 'instr' and name:
            self.runs.append({'field': name})

    def _para_end(self):
        para = self._paragraph()
        self.runs = []
        if self.table_rows is not None and (self.row_cells or self.cell_paras):
            self.cell_paras.append(para)
        else:
            self._close_table()
            self.blocks.append(para)

    def _cell_or_row_end(self):
        if self.prev == '\x07':
            if self.table_rows is None:
                self.table_rows = []
            self.table_rows.append(self.row_cells)
            self.row_cells = []
            self.cell_paras = []
            self.runs = []
            return
        paras = self.cell_paras + [self._paragraph()]
        self.runs = []
        self.cell_paras = []
        self.row_cells.append({'span': 1, 'paras': paras})
        if self.table_rows is None:
            self.table_rows = []

    def feed(self, text):
        for ch in text:
            self._feed_char(ch)
            self.prev = ch
        if self.runs:
            self.blocks.append(self._paragraph())
        self._close_table()
        return self.blocks

    def _feed_char(self, ch):
        if ch == '\x13':
            self._field_begin()
            return
        if ch == '\x14' and self.stack:
            self._field_separate()
            return
        if ch == '\x15' and self.stack:
            self._field_end()
            return
        if self.stack and self.stack[-1]['stage'] == 'instr':
            self.stack[-1]['instr'] += ch
            return
        if any(entry['merge'] for entry in self.stack):
            return
        if ch == '\r':
            self._para_end()
        elif ch == '\x07':
            self._cell_or_row_end()
        elif ch == '\x0b':
            self.runs.append({'br': True})
        elif ch == '\t':
            self.runs.append({'text': '\t'})
        elif ch >= ' ' or ch == '\xa0':
            self.runs.append({'text': ch})


def read_doc_blocks(doc_bytes):
    """Xem docstring đầu module."""
    ole = _Ole(doc_bytes)
    word = ole.stream('WordDocument')
    if word is None or len(word) < 0x1AA:
        raise ValueError('File .doc thiếu luồng WordDocument')
    if struct.unpack_from('<H', word, 0)[0] != 0xA5EC:
        raise ValueError('File .doc không hợp lệ (wIdent sai)')
    flags = struct.unpack_from('<H', word, 0x0A)[0]
    table_stream = ole.stream('1Table' if flags & 0x0200 else '0Table')
    if table_stream is None:
        raise ValueError('File .doc thiếu luồng bảng (0Table/1Table)')
    text = _piece_text(word, table_stream)
    ccp_text = struct.unpack_from('<i', word, 0x4C)[0]
    if ccp_text > 0:
        text = text[:ccp_text]
    return _BlockBuilder().feed(text)
