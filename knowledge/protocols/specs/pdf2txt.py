# -*- coding: utf-8 -*-
"""Minimal stdlib-only PDF text extractor for Word-exported Modbus spec PDFs.

Parses PDF objects (incl. object streams), walks the page tree, inflates
FlateDecode content streams, decodes Tj/TJ/'/" text operators with
ToUnicode CMap support, and writes one UTF-8 text file per PDF with
per-page markers  ===== [PAGE n] =====  (n = 1-based physical PDF page).
"""
import re
import sys
import zlib
import os

WS = b' \t\r\n\x0c\x00'


def skip_string(d, j):
    # d[j] == '(' ; return index just after the closing paren
    depth = 1
    k = j + 1
    n = len(d)
    while k < n and depth:
        ch = d[k:k + 1]
        if ch == b'\\':
            k += 2
            continue
        if ch == b'(':
            depth += 1
        elif ch == b')':
            depth -= 1
        k += 1
    return k


def skip_hex(d, j):
    e = d.find(b'>', j)
    return (e + 1) if e != -1 else len(d)


def read_value(d, j):
    """Read one PDF token starting at position j inside dict/array bytes.
    Returns (value_bytes, end_index)."""
    n = len(d)
    while j < n and d[j:j + 1] in WS:
        j += 1
    if j >= n:
        return (b'', j)
    c = d[j:j + 1]
    if c == b'(':
        k = skip_string(d, j)
        return (d[j:k], k)
    if c == b'<':
        if d[j:j + 2] == b'<<':
            depth = 0
            k = j
            while k < n:
                if d[k:k + 1] == b'(':
                    k = skip_string(d, k)
                    continue
                if d[k:k + 2] == b'<<':
                    depth += 1
                    k += 2
                elif d[k:k + 2] == b'>>':
                    depth -= 1
                    k += 2
                    if depth == 0:
                        break
                else:
                    k += 1
            return (d[j:k], k)
        k = skip_hex(d, j)
        return (d[j:k], k)
    if c == b'[':
        depth = 0
        k = j
        while k < n:
            if d[k:k + 1] == b'(':
                k = skip_string(d, k)
                continue
            if d[k:k + 1] == b'[':
                depth += 1
                k += 1
            elif d[k:k + 1] == b']':
                depth -= 1
                k += 1
                if depth == 0:
                    break
                continue
            else:
                k += 1
        return (d[j:k], k)
    if c == b'/':
        k = j + 1
        while k < n and d[k:k + 1] not in WS and d[k:k + 1] not in b'/<>[](){}%':
            k += 1
        return (d[j:k], k)
    k = j
    while k < n and d[k:k + 1] not in WS and d[k:k + 1] not in b'/<>[](){}%':
        k += 1
    if k == j:
        return (b'', j + 1)
    mref = re.match(rb'\s+(\d+)\s+R\b', d[k:k + 64])
    if mref:
        k += mref.end()
    return (d[j:k], k)


def dict_value(d, key):
    """Value for /Key at top level of dict bytes; returns raw token or None."""
    return dict_entries(d).get(key.lstrip(b'/'))


def dict_entries(d):
    """Parse top-level /Key value pairs of a dict; returns {keybytes: valbytes}."""
    out = {}
    if d is None:
        return out
    k = 0
    n = len(d)
    while k < n and d[k:k + 1] in WS:
        k += 1
    if d[k:k + 2] == b'<<':
        k += 2
    while k < n:
        c = d[k:k + 1]
        if c in WS:
            k += 1
            continue
        if d[k:k + 2] == b'>>':
            break
        if c == b'/':
            j = k + 1
            while j < n and d[j:j + 1] not in WS and d[j:j + 1] not in b'/<>[](){}%':
                j += 1
            key = d[k + 1:j]
            val, k2 = read_value(d, j)
            out[key] = val
            k = k2 if k2 > k else k + 1
        elif c == b'(':
            k = skip_string(d, k)
        elif c == b'<':
            if d[k:k + 2] == b'<<':
                v, k2 = read_value(d, k)
                k = k2
            else:
                k = skip_hex(d, k)
        elif c == b'[':
            v, k2 = read_value(d, k)
            k = k2
        elif c == b'%':
            e = d.find(b'\n', k)
            k = (e + 1) if e != -1 else n
        else:
            k += 1
    return out


def array_tokens(arr):
    toks = []
    if arr is None:
        return toks
    k = 1
    n = len(arr)
    while k < n:
        c = arr[k:k + 1]
        if c in WS or c == b']':
            k += 1
            continue
        val, k2 = read_value(arr, k)
        if val:
            toks.append(val)
        k = k2 if k2 > k else k + 1
    return toks


class Pdf:
    def __init__(self, data):
        self.data = data
        self.objs = {}
        if re.search(rb'/Encrypt\s+\d+\s+\d+\s+R', data):
            raise RuntimeError('encrypted PDF')
        self._parse_objects()
        self._expand_objstm()

    # ---------- object layer ----------
    def _parse_objects(self):
        data = self.data
        obj_re = re.compile(rb'(\d+)\s+(\d+)\s+obj\b')
        stream_re = re.compile(rb'\bstream(\r\n|\r|\n)')
        endobj_re = re.compile(rb'\bendobj\b')
        endstream_re = re.compile(rb'\bendstream')
        pos = 0
        while True:
            m = obj_re.search(data, pos)
            if not m:
                break
            num = int(m.group(1))
            start = m.end()
            em = endobj_re.search(data, start)
            sm = stream_re.search(data, start)
            if sm and (not em or sm.start() < em.start()):
                d = data[start:sm.start()]
                s_start = sm.end()
                se = endstream_re.search(data, s_start)
                raw = data[s_start:se.start() if se else len(data)]
                if raw.endswith(b'\r\n'):
                    raw = raw[:-2]
                elif raw.endswith(b'\r') or raw.endswith(b'\n'):
                    raw = raw[:-1]
                self.objs[num] = [d, raw]
                pos = se.end() if se else len(data)
            else:
                d = data[start:em.start() if em else len(data)]
                self.objs[num] = [d, None]
                pos = em.end() if em else len(data)

    @staticmethod
    def inflate(s):
        try:
            return zlib.decompress(s)
        except Exception:
            d = zlib.decompressobj(-15)
            return d.decompress(s) + d.flush()

    def _expand_objstm(self):
        for num in list(self.objs.keys()):
            d, s = self.objs[num]
            if s is None or not re.search(rb'/ObjStm\b', d):
                continue
            try:
                blob = self.inflate(s)
            except Exception:
                continue
            mN = re.search(rb'/N\s+(\d+)', d)
            mF = re.search(rb'/First\s+(\d+)', d)
            if not (mN and mF):
                continue
            N = int(mN.group(1))
            First = int(mF.group(1))
            hdr = blob[:First].split()
            if len(hdr) < 2 * N:
                continue
            pairs = [(int(hdr[2 * i]), int(hdr[2 * i + 1])) for i in range(N)]
            for i, (onum, off) in enumerate(pairs):
                endoff = pairs[i + 1][1] if i + 1 < len(pairs) else len(blob) - First
                self.objs[onum] = [blob[First + off:First + endoff], None]

    def deref(self, tok):
        """tok: ref token bytes -> (dictbytes, streambytes-or-None)."""
        if tok is None:
            return (None, None)
        t = tok.strip()
        m = re.match(rb'^(\d+)\s+\d+\s+R$', t)
        if m:
            return self.objs.get(int(m.group(1)), (None, None))
        return (t, None)

    # ---------- page tree ----------
    def catalog(self):
        for num, (d, s) in self.objs.items():
            if d and re.search(rb'/Type\s*/Catalog\b', d):
                return d
        return None

    def pages_in_order(self):
        root = self.catalog()
        pages_root = self.deref(dict_value(root, b'/Pages'))[0]
        out = []
        self._walk(pages_root, out, 0)
        return out

    def _walk(self, node_d, out, depth):
        if node_d is None or depth > 64:
            return
        if re.search(rb'/Type\s*/Page\b', node_d) and b'/Kids' not in node_d:
            out.append(node_d)
            return
        kids = dict_value(node_d, b'/Kids')
        for tok in array_tokens(kids):
            d, _s = self.deref(tok)
            self._walk(d, out, depth + 1)

    def inherited_resources(self, page_d):
        seen = page_d
        hops = 0
        while seen is not None and hops < 64:
            r = dict_value(seen, b'/Resources')
            if r is not None:
                rd, _ = self.deref(r)
                return rd if rd is not None else r
            par = dict_value(seen, b'/Parent')
            seen, _ = self.deref(par)
            hops += 1
        return None


# ---------- fonts ----------
def parse_tounicode(blob):
    cmap = {}
    for m in re.finditer(rb'beginbfchar(.*?)endbfchar', blob, re.S):
        for mm in re.finditer(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', m.group(1)):
            src = int(mm.group(1), 16)
            h = mm.group(2).decode()
            dst = ''.join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4))
            cmap[src] = dst
    for m in re.finditer(rb'beginbfrange(.*?)endbfrange', blob, re.S):
        body = m.group(1)
        for mm in re.finditer(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])',
                              body, re.S):
            lo = int(mm.group(1), 16)
            hi = int(mm.group(2), 16)
            if hi < lo or hi - lo > 65535:
                continue
            tgt = mm.group(3)
            if tgt.startswith(b'<'):
                basehex = tgt[1:-1].decode()
                width = len(basehex)
                base = int(basehex, 16)
                for c in range(lo, hi + 1):
                    v = base + (c - lo)
                    cmap[c] = chr(v) if v <= 0x10FFFF else '?'
            else:
                vals = re.findall(rb'<([0-9A-Fa-f]+)>', tgt)
                for i, c in enumerate(range(lo, hi + 1)):
                    if i < len(vals):
                        h = vals[i].decode()
                        cmap[c] = ''.join(chr(int(h[j:j + 4], 16))
                                          for j in range(0, len(h), 4))
    return cmap


def build_font(pdf, font_val):
    """font_val: ref token or inline dict -> decoder tuple."""
    d, s = pdf.deref(font_val)
    d = d if d is not None else font_val
    if d is None:
        return ('s1', {}, b'')
    subtype = (dict_value(d, b'/Subtype') or b'').strip()
    base = b''
    enc = dict_value(d, b'/Encoding')
    if enc is not None:
        if enc.startswith(b'/'):
            base = enc.strip()
        else:
            be = dict_value(enc, b'/BaseEncoding')
            base = be.strip() if be else b''
    tmap = {}
    tu = dict_value(d, b'/ToUnicode')
    if tu is not None:
        td, ts = pdf.deref(tu)
        if ts is not None:
            try:
                blob = Pdf.inflate(ts)
            except Exception:
                blob = ts
            tmap = parse_tounicode(blob)
    is_type0 = (subtype == b'/Type0')
    if is_type0:
        e = (dict_value(d, b'/Encoding') or b'').strip()
        width = 2 if (b'Identity' in e or b'H' == e[-1:] or not e.startswith(b'/')) else 2
        return ('t0', width, tmap)
    return ('s1', tmap, base)


def decode_string(font, b):
    if not b:
        return ''
    if font[0] == 't0':
        width, tmap = font[1], font[2]
        out = []
        for i in range(0, len(b) - width + 1, width):
            code = int.from_bytes(b[i:i + width], 'big')
            if code in tmap:
                out.append(tmap[code])
            else:
                lo = code & 0xFF
                out.append(chr(lo) if 32 <= lo < 127 else '')
        return ''.join(out)
    tmap = font[1]
    out = []
    for code in b:
        if code in tmap:
            out.append(tmap[code])
        elif 32 <= code < 127:
            out.append(chr(code))
        else:
            out.append(bytes([code]).decode('cp1252', 'replace'))
    return ''.join(out)


# ---------- content stream ----------
def unescape_literal(s):
    out = bytearray()
    i = 0
    n = len(s)
    while i < n:
        c = s[i:i + 1]
        if c != b'\\':
            out += c
            i += 1
            continue
        i += 1
        if i >= n:
            break
        c = s[i:i + 1]
        if c in b'nrtbf':
            out += {b'n': b'\n', b'r': b'\r', b't': b'\t', b'b': b'\b', b'f': b'\f'}[c]
            i += 1
        elif c in b'()\\':
            out += c
            i += 1
        elif c in b'01234567':
            oct_digits = s[i:i + 3]
            m = re.match(rb'[0-7]{1,3}', oct_digits)
            out.append(int(m.group(0), 8))
            i += len(m.group(0))
        elif c == b'\r':
            i += 2 if s[i + 1:i + 2] == b'\n' else 1
        elif c == b'\n':
            i += 1
        else:
            out += c
            i += 1
    return bytes(out)


def content_events(content):
    """Yield ('tok', bytes) and ('str', bytes) and ('arr', bytes) events."""
    i = 0
    n = len(content)
    while i < n:
        c = content[i:i + 1]
        if c == b'(':
            j = skip_string(content, i)
            yield ('str', unescape_literal(content[i + 1:j - 1]))
            i = j
        elif c == b'<' and content[i:i + 2] == b'<<':
            # inline dict (e.g. BDC/DP property list): skip balanced, strings aware
            depth = 0
            j = i
            while j < n:
                if content[j:j + 1] == b'(':
                    j = skip_string(content, j)
                    continue
                if content[j:j + 2] == b'<<':
                    depth += 1
                    j += 2
                elif content[j:j + 2] == b'>>':
                    depth -= 1
                    j += 2
                    if depth == 0:
                        break
                else:
                    j += 1
            yield ('dict', content[i:j])
            i = j
        elif c == b'<':
            j = skip_hex(content, i)
            hx = re.sub(rb'\s', b'', content[i + 1:j - 1])
            if len(hx) % 2:
                hx += b'0'
            try:
                yield ('str', bytes.fromhex(hx.decode()))
            except Exception:
                yield ('str', b'')
            i = j
        elif c == b'[':
            depth = 0
            j = i
            while j < n:
                if content[j:j + 1] == b'(':
                    j = skip_string(content, j)
                    continue
                if content[j:j + 1] == b'[':
                    depth += 1
                    j += 1
                elif content[j:j + 1] == b']':
                    depth -= 1
                    j += 1
                    if depth == 0:
                        break
                    continue
                else:
                    j += 1
            yield ('arr', content[i:j])
            i = j
        elif c == b'/':
            j = i + 1
            while j < n and content[j:j + 1] not in WS and content[j:j + 1] not in b'/<>[](){}%':
                j += 1
            yield ('name', content[i + 1:j])
            i = j
        elif c == b'%':
            e = content.find(b'\n', i)
            i = (e + 1) if e != -1 else n
        elif c in WS or c in b'<>]{}':
            i += 1
        else:
            j = i
            while j < n and content[j:j + 1] not in WS and content[j:j + 1] not in b'/<>[](){}%':
                j += 1
            if j == i:
                i += 1
                continue
            yield ('tok', content[i:j])
            i = j


def extract_page_text(pdf, page_d):
    res = pdf.inherited_resources(page_d)
    fonts = {}
    if res is not None:
        fdict = dict_value(res, b'/Font')
        for key, val in dict_entries(fdict).items():
            fonts[key] = build_font(pdf, val)
    # gather content streams
    parts = []
    cval = dict_value(page_d, b'/Contents')
    if cval is None:
        return ''
    if cval.startswith(b'['):
        for tok in array_tokens(cval):
            _d, s = pdf.deref(tok)
            if s is not None:
                try:
                    parts.append(Pdf.inflate(s))
                except Exception:
                    parts.append(s)
    else:
        _d, s = pdf.deref(cval)
        if s is not None:
            try:
                parts.append(Pdf.inflate(s))
            except Exception:
                parts.append(s)
    content = b'\n'.join(parts)

    out = []
    line_open = [False]
    cur_y = [None]
    tl = [0.0]
    cur_font = [None]
    stack = []
    budget = [20 * 1000 * 1000]

    def tick():
        budget[0] -= 1
        if budget[0] <= 0:
            raise RuntimeError('content event budget exhausted')

    def emit(t):
        if t:
            out.append(t)
            line_open[0] = True

    def newline():
        if line_open[0]:
            out.append('\n')
            line_open[0] = False

    def show_string(b):
        f = cur_font[0]
        emit(decode_string(f, b) if f else decode_string(('s1', {}, b''), b))

    def last_string_from_stack():
        for kind, val in reversed(stack):
            if kind == 'str':
                return val
        return b''

    def arr_text(arr):
        body = arr
        if body.startswith(b'['):
            body = body[1:]
        if body.endswith(b']'):
            body = body[:-1]
        segs = []
        for kind, val in content_events(body):
            if kind == 'str':
                f = cur_font[0]
                segs.append(decode_string(f, val) if f else val.decode('cp1252', 'replace'))
        return ''.join(segs)

    def last_number(default=0.0):
        for kind, val in reversed(stack):
            if kind == 'tok':
                try:
                    return float(val)
                except Exception:
                    return default
        return default

    TEXT_OPS = {
        b'Tj', b'TJ', b"'", b'"', b'Tf', b'Td', b'TD', b'Tm', b'T*', b'TL',
        b'BT', b'ET', b'Tc', b'Tw', b'Tz', b'Ts', b'Tr',
        b'q', b'Q', b'cm', b're', b'W', b'W*', b'n', b'f', b'f*', b'B', b'B*',
        b'b', b'b*', b'S', b's', b'gs', b'rg', b'g', b'k', b'K', b'G', b'g',
        b'EMC', b'BMC', b'BDC', b'DP', b'MP', b'Do', b'sh', b'BI', b'ID', b'EI',
        b'cs', b'CS', b'sc', b'scn', b'SC', b'SCN', b'i', b'j', b'J', b'M',
        b'd', b'm', b'l', b'c', b'v', b'y', b'h', b'ri', b'd0', b'd1',
    }
    for kind, val in content_events(content):
        tick()
        if kind in ('str', 'arr', 'dict'):
            stack.append((kind, val))
            continue
        if kind == 'name':
            stack.append(('name', val))
            continue
        op = val
        if op not in TEXT_OPS:
            stack.append(('tok', val))
            continue
        if op == b'Tj':
            show_string(last_string_from_stack())
        elif op == b'TJ':
            for k2, v2 in reversed(stack):
                if k2 == 'arr':
                    emit(arr_text(v2))
                    break
        elif op in (b"'", b'"'):
            newline()
            show_string(last_string_from_stack())
        elif op == b'Tf':
            f = None
            for k2, v2 in reversed(stack):
                if k2 == 'name':
                    f = fonts.get(v2.lstrip(b'/'))
                    break
            cur_font[0] = f
        elif op in (b'Td', b'TD'):
            ty = last_number()
            if cur_y[0] is not None:
                ny = cur_y[0] + ty
            else:
                ny = ty
            if abs(ty) > 0.25:
                newline()
            elif line_open[0]:
                emit(' ')
            cur_y[0] = ny
            if op == b'TD':
                tl[0] = -ty
        elif op == b'Tm':
            ty = last_number()
            if cur_y[0] is None:
                cur_y[0] = ty
            elif abs(ty - cur_y[0]) > 0.25:
                newline()
                cur_y[0] = ty
            elif line_open[0]:
                emit(' ')
        elif op == b'T*':
            cur_y[0] = (cur_y[0] or 0.0) - tl[0]
            newline()
        elif op == b'TL':
            tl[0] = last_number()
        elif op == b'BT':
            newline()
        elif op == b'ET':
            newline()
        stack = []

    text = ''.join(out)
    # tidy: drop NUL/control junk, collapse >2 blank lines, strip trailing ws
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def convert(pdf_path, txt_path):
    with open(pdf_path, 'rb') as fh:
        data = fh.read()
    pdf = Pdf(data)
    pages = pdf.pages_in_order()
    print('parsed objects=%d pages=%d' % (len(pdf.objs), len(pages)), flush=True)
    chunks = []
    total = 0
    for idx, page_d in enumerate(pages, 1):
        print('  extracting page %d/%d ...' % (idx, len(pages)), flush=True)
        t = extract_page_text(pdf, page_d)
        total += len(t)
        chunks.append('===== [PAGE %d] =====\n%s' % (idx, t))
        print('  page %d/%d chars=%d' % (idx, len(pages), len(t)), flush=True)
    with open(txt_path, 'w', encoding='utf-8', newline='') as fh:
        fh.write('\n'.join(chunks))
    return len(pages), total


def main():
    outdir = sys.argv[1]
    for pdf_path in sys.argv[2:]:
        name = os.path.splitext(os.path.basename(pdf_path))[0]
        txt_path = os.path.join(outdir, name + '.txt')
        try:
            pages, chars = convert(pdf_path, txt_path)
            print('%s: pages=%d chars=%d -> %s' % (name, pages, chars, txt_path))
        except Exception as exc:
            print('%s: FAILED %s' % (name, exc))


if __name__ == '__main__':
    main()
