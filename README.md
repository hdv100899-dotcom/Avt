# Avt — OSINT Dashboard

Hệ thống tự động thu thập, lưu trữ, chống trùng và phân tích tin quân sự, quốc phòng từ nguồn công khai.
Thiết kế và lộ trình: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Trạng thái

Giai đoạn 0 (khung dự án): schema CSDL, migration, Source Registry, CLI, kiểm thử, CI.
Chưa có Collector (giai đoạn 1).

## Chạy thử

```bash
docker compose up -d db                    # PostgreSQL 16 + pgvector
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env && export $(grep -v '^#' .env | xargs)
alembic upgrade head

osint source add rss https://example.org/feed.xml --name "Example" --language en
osint source list
```

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
