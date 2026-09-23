# Sentinel-2 Monitor

Ứng dụng web chạy từ một file duy nhất, dùng để rà soát các mục tiêu xem đã có ảnh Sentinel-2 mới hay chưa. App đo mây trong đúng khung mục tiêu và tải ảnh đã cắt sẵn theo vùng.

## Chạy
- **Windows**: bấm đúp `run.bat` (cần Python 3). App mở ở `http://localhost:8765/`; ảnh tải về **tự vào kho chung `D:\KHO_ANH\TD\<Ten_muc_tieu>\`**. Đổi đường dẫn ở dòng `set KHO_ANH=...` trong run.bat.
- **Linux/macOS**: `./run.sh`
- Hoặc bấm đúp `index.html`.

Cần kết nối Internet để truy cập Microsoft Planetary Computer, Copernicus Data Space và cdnjs.

## Tính năng chính
- Quét song song mọi mục tiêu. Trạng thái tính theo **ngày lịch giờ VN**: Hôm nay, Hôm qua, N ngày trước.
- **Mây trong vùng mục tiêu**, tính từ lớp phân loại SCL, thay cho mây của cả ô 110 km.
- **Dự báo ngày bay kế tiếp** dựa trên chu kỳ lặp 10 ngày của S2A, S2B và S2C.
- Báo “Đã chụp, chờ PC” khi Copernicus đã có ảnh mà Planetary Computer chưa có.
- Ảnh cắt theo vùng ở 4 kiểu hiển thị: Màu thật, Hồng ngoại, SWIR, NDVI. So sánh hai ngày bằng thanh trượt.
- Khung nhìn mở rộng tới 40 km (không bó trong ô geo). Bản đồ hiện toàn bộ cảnh 110 km.
- Tải ở **độ phân giải gốc**:
  - JPG hoặc GeoTIFF 10 m theo khung nhìn.
  - **Tick chọn ảnh rồi bấm Tải TCI**:
    - Mặc định: **TCI L1C cắt theo khung**, dạng JP2 gốc 10 m, pixel trùng khớp file gốc. Chỉ tải vài MB thay vì cả ô 120 MB; cần `rasterio`, `run.bat` tự cài.
    - Hoặc TCI L1C cả ô.
    - Hoặc TCI L2A cắt theo khung (GeoTIFF).
  - Cả ô gốc.
  - ZIP ảnh mới của mọi mục tiêu kèm file CSV.
- **Kho ảnh chung** `D:\KHO_ANH\TD`: máy chủ cục bộ `server.py` ghi ảnh (JPG + `.jgw`/`.prj`, GeoTIFF, TCI L1C) vào thư mục của từng mục tiêu, tự tải file lớn thẳng từ nguồn. Tab Kho ảnh để xem lại.
- **Nhập geo hàng loạt**:
  - Chọn file, chọn **cả thư mục** (kể cả thư mục con), hoặc kéo thả cả thư mục chứa `.geojson`/`.kml`/`.csv`.
  - File một đối tượng thì lấy tên file làm tên mục tiêu (quy ước `DIABAN_LOAI_LUCLUONG_STT_Ten`).
  - Nhóm lấy theo thư mục con chứa file, hoặc theo mã địa bàn đầu tên file.
  - Có bảng xem trước từng mục (Mới / Cập nhật tọa độ / Đã có) để tick chọn. Trùng tên thì cập nhật chứ không nhân đôi. Có thể quét ngay sau khi nhập.
- Bản đồ Leaflet. Xuất GeoJSON.
- Tự quét lại định kỳ và gửi thông báo hệ thống khi có ảnh mới.

## Cấu trúc
| Đường dẫn | Nội dung |
|---|---|
| `index.html` | Ứng dụng |
| `server.py` | Máy chủ cục bộ: phục vụ app + ghi vào kho ảnh chung |
| `run.bat`, `run.sh` | Khởi chạy (đặt đường dẫn kho `KHO_ANH`) |
| `docs/NGHIEN_CUU.md` | Nghiên cứu: lỗi của bản cũ, kết quả thử API, thiết kế |
| `legacy/` | Bản cũ để đối chiếu |
