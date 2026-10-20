# Avt — OSINT Dashboard

Hệ thống tự động thu thập, lưu trữ, chống trùng và phân tích tin quân sự, quốc phòng từ nguồn công khai.
Thiết kế và lộ trình: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Trạng thái

- Giai đoạn 0 xong: schema CSDL, migration, Source Registry, CLI, kiểm thử, CI.
- Giai đoạn 1 đang làm: Collector RSS/Atom (gọi có điều kiện, chu kỳ tự điều chỉnh, lấy toàn văn có
  tôn trọng robots.txt), kho snapshot bất biến, dashboard luồng tin, thống kê độ trễ.
- Chưa có: chống trùng (GĐ2), Telegram, AI, bản tin.

## Chạy thử

```bash
docker compose up -d db                    # PostgreSQL 16 + pgvector
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env && export $(grep -v '^#' .env | xargs)
alembic upgrade head

osint source seed config/sources.en.json   # 10 nguồn quốc phòng tiếng Anh đã kiểm tra
osint collect once                         # thu thập một lượt
osint collect run                          # chạy liên tục
osint web                                  # dashboard tại http://127.0.0.1:8000
osint stats                                # số tin và độ trễ trung vị theo nguồn

osint source add rss https://example.org/feed.xml --name "Example" --language en
osint source list
```

Dữ liệu snapshot nằm ở `data/` (đổi bằng `OSINT_DATA_DIR`). API: `/api/items`, `/api/sources`.

### Giới hạn đã biết

- Một số trang (ví dụ Army/Naval/Airforce Technology) chặn client Python bằng 403 dù feed công khai.
  Dự án không giả dạng trình duyệt để né chặn, nên các nguồn này không có trong bộ seed.
- Lần thăm dò đầu tiên của mỗi nguồn lấy cả bài cũ trong feed; `osint stats` bỏ các bài đó khi tính độ trễ.
- Bài trả phí chỉ có đoạn mở đầu trong feed; hệ thống giữ nguyên đoạn đó nếu trang không cho nhiều hơn.

`docker-compose.yml` chưa được chạy thử trong môi trường phát triển (không có Docker daemon);
migration và kiểm thử đã chạy trên PostgreSQL 16 cài trực tiếp.

## Kiểm thử

Cần một PostgreSQL có extension `vector`. Mặc định kiểm thử kết nối
`postgresql+psycopg://postgres@localhost:5433/postgres` (đổi bằng `OSINT_TEST_ADMIN_URL`);
mỗi lần chạy tạo và xóa cơ sở dữ liệu tạm.

```bash
pytest -q
ruff check . && ruff format --check .
```
