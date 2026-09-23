#!/usr/bin/env python3
"""Máy chủ cục bộ cho Sentinel-2 Monitor.

- Phục vụ index.html tại http://localhost:<PORT>/
- Ghi ảnh tải về vào KHO ẢNH CHUNG: <KHO_ANH>\\<Ten_muc_tieu>\\<tệp>
  (mặc định D:\\KHO_ANH\\TD trên Windows)
- Tự tải file lớn (TCI L1C, GeoTIFF) thẳng từ nguồn vào kho, không qua trình duyệt

Chỉ dùng thư viện chuẩn của Python 3.8+.

    python server.py [--kho D:\\KHO_ANH\\TD] [--port 8765]

Biến môi trường KHO_ANH / PORT cũng được chấp nhận.
"""
import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_KHO = r"D:\KHO_ANH\TD" if os.name == "nt" else os.path.expanduser("~/KHO_ANH/TD")

# Chỉ cho máy chủ tự tải từ các nguồn ảnh mà app dùng
ALLOWED_HOSTS = (
    "planetarycomputer.microsoft.com",
    "storage.googleapis.com",
    ".blob.core.windows.net",
)
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_part(s, allow_empty=False):
    """Một thành phần đường dẫn an toàn (không '..', không ký tự cấm của Windows)."""
    s = BAD_CHARS.sub("_", str(s or "")).strip().rstrip(". ")
    if s in ("", ".", ".."):
        if allow_empty and not s:
            return ""
        raise ValueError("tên không hợp lệ")
    return s[:120]


class Handler(SimpleHTTPRequestHandler):
    server_version = "S2Monitor/1.0"
    kho = DEFAULT_KHO
    port = 8765

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=APP_DIR, **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ---- tiện ích ----
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        # Chống DNS rebinding: chỉ nhận Host là localhost/127.0.0.1
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("localhost", "127.0.0.1")

    def _api_ok(self):
        # Header riêng: trang web khác không gửi được nếu không qua preflight CORS (mà máy chủ này không cho)
        return self._host_ok() and self.headers.get("X-S2M") == "1"

    def _target_path(self, folder, sub, name):
        parts = [safe_part(folder)]
        if sub:
            parts.append(safe_part(sub))
        parts.append(safe_part(name))
        d = os.path.join(self.kho, *parts[:-1])
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, parts[-1])

    @staticmethod
    def _write_stream(src, dest, length=None):
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            if length is None:
                shutil.copyfileobj(src, f, 1 << 20)
            else:
                left = length
                while left > 0:
                    chunk = src.read(min(1 << 20, left))
                    if not chunk:
                        raise IOError("kết nối bị ngắt giữa chừng")
                    f.write(chunk)
                    left -= len(chunk)
        os.replace(tmp, dest)
        return os.path.getsize(dest)

    def _body_len(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise ValueError("yêu cầu không có dữ liệu")
        return n

    # ---- GET ----
    def do_GET(self):
        if not self._host_ok():
            return self.send_error(403)
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/health":
            return self._json(200, {"ok": True, "app": "s2m", "root": self.kho, "sep": os.sep})
        if u.path == "/api/list":
            return self._list()
        if u.path == "/api/file":
            return self._file(urllib.parse.parse_qs(u.query).get("path", [""])[0])
        if u.path in ("/", ""):
            self.path = "/index.html"
        if u.path.endswith(".py"):
            return self.send_error(404)
        return super().do_GET()

    def _list(self):
        folders = []
        if os.path.isdir(self.kho):
            for name in sorted(os.listdir(self.kho)):
                top = os.path.join(self.kho, name)
                if not os.path.isdir(top):
                    continue
                files = []
                for dirpath, _, fnames in os.walk(top):
                    for fn in fnames:
                        if fn.endswith(".part"):
                            continue
                        fp = os.path.join(dirpath, fn)
                        st = os.stat(fp)
                        files.append({"path": os.path.relpath(fp, top).replace(os.sep, "/"), "name": fn,
                                      "size": st.st_size, "mtime": int(st.st_mtime * 1000)})
                folders.append({"name": name, "files": files})
        return self._json(200, {"ok": True, "root": self.kho, "folders": folders})

    def _file(self, rel):
        fp = os.path.realpath(os.path.join(self.kho, *[p for p in rel.split("/") if p not in ("", ".", "..")]))
        if not fp.startswith(os.path.realpath(self.kho) + os.sep) or not os.path.isfile(fp):
            return self.send_error(404)
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(os.path.getsize(fp)))
        self.end_headers()
        with open(fp, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    # ---- POST ----
    def do_POST(self):
        if not self._api_ok():
            return self._json(403, {"ok": False, "error": "forbidden"})
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/api/save":
                q = urllib.parse.parse_qs(u.query)
                g = lambda k: q.get(k, [""])[0]
                n = self._body_len()
                dest = self._target_path(g("folder"), g("sub"), g("name"))
                size = self._write_stream(self.rfile, dest, n)
                return self._json(200, {"ok": True, "path": dest, "size": size})
            if u.path == "/api/fetch":
                req = json.loads(self.rfile.read(self._body_len()))
                src = urllib.parse.urlparse(req.get("url", ""))
                host = (src.hostname or "").lower()
                if src.scheme != "https" or not any(host == h or (h.startswith(".") and host.endswith(h)) for h in ALLOWED_HOSTS):
                    return self._json(400, {"ok": False, "error": "nguồn không được phép: " + host})
                dest = self._target_path(req.get("folder"), req.get("sub"), req.get("name"))
                r = urllib.request.urlopen(urllib.request.Request(req["url"], headers={"User-Agent": "S2Monitor/1.0"}), timeout=120)
                size = self._write_stream(r, dest)
                return self._json(200, {"ok": True, "path": dest, "size": size})
            return self._json(404, {"ok": False, "error": "không có API này"})
        except Exception as e:  # noqa: BLE001 — trả lỗi cho giao diện hiển thị
            return self._json(500, {"ok": False, "error": str(e)})


def main():
    ap = argparse.ArgumentParser(description="Sentinel-2 Monitor — máy chủ cục bộ + kho ảnh")
    ap.add_argument("--kho", default=os.environ.get("KHO_ANH") or DEFAULT_KHO, help="thư mục kho ảnh chung")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8765))
    a = ap.parse_args()
    Handler.kho = os.path.abspath(a.kho)
    Handler.port = a.port
    os.makedirs(Handler.kho, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print("Sentinel-2 Monitor: http://localhost:%d/" % a.port)
    print("Kho anh chung    : %s" % Handler.kho)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
