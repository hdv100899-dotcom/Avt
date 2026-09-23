# Nghiên cứu và thiết kế lại app kiểm tra ảnh Sentinel-2

Tài liệu này ghi lại những gì đã kiểm tra trên bản cũ (`legacy/Sentinel-2_Monitor.html`, `legacy/run.bat`), kết quả thử trực tiếp các API, và các quyết định thiết kế của bản mới (`index.html`).

Các phép thử API chạy ngày 23/09/2026 lúc khoảng 07:30–07:50 giờ VN.

## 1. Lỗi và hạn chế của bản cũ

| # | Vấn đề | Hậu quả | Bản mới xử lý |
|---|--------|---------|---------------|
| 1 | Gọi `POST /api/stac/v1/search` với `Content-Type: application/json`. API STAC của Planetary Computer trả **405** cho yêu cầu preflight `OPTIONS`. | Trình duyệt chặn CORS, **mọi lượt quét đều thất bại âm thầm** và mục tiêu cứ ở trạng thái “Chưa quét”. Đã tái hiện bằng Chromium. | Dùng `GET /search?...`: yêu cầu “simple”, không cần preflight. |
| 2 | `run.bat` chạy `streamlit run app.py`, nhưng không có `app.py`. | File chạy không dùng được. | `run.bat` mới mở `index.html` qua `python -m http.server`, hoặc mở thẳng file nếu máy không có Python. |
| 3 | Tính “hôm nay” bằng `floor((now − thời điểm chụp) / 24h)`. | Ảnh chụp 10:30 hôm qua, lúc 09:00 sáng nay mới được 22,5 giờ, nên bị báo **“VỪA CHỤP HÔM NAY”**. | So sánh **ngày lịch theo giờ VN** (`YYYY-MM-DD`). |
| 4 | Chỉ lấy `limit: 1` cảnh mới nhất và dùng `eo:cloud_cover` của cả ô. | Mây của ô 110×110 km không phản ánh mây tại mục tiêu. Đo thật: một cảnh ở Long Thành có **ô 29% mây, còn trong vùng mục tiêu 99%**. | Đo mây **trong đúng khung mục tiêu** bằng lớp SCL, cho N lượt gần nhất. |
| 5 | “Tải nhanh” là `rendered_preview`, tức ảnh xem trước của **cả ô 110 km**. | Mục tiêu 7 km chỉ chiếm vài chục pixel trong ảnh tải về. | Cắt ảnh theo khung mục tiêu bằng `/api/data/v1/item/bbox/...` ở độ phân giải gốc 10 m. |
| 6 | “Ảnh gốc” là toàn bộ `visual.tif` (100–250 MB). Token SAS được cache 1 giờ và lưu vào localStorage cùng URL. | Tải nặng. Token thực tế chỉ sống khoảng 45 phút (`msft:expiry`), nên link lưu lại sẽ hết hạn. | Thêm **GeoTIFF đã cắt theo vùng** (~2 MB, có tọa độ). Link cả ô chỉ ký lúc bấm, theo `msft:expiry`. |
| 7 | Chèn tên mục tiêu vào `innerHTML` và vào chuỗi `onclick='...'`. | Tên có dấu `'` làm hỏng nút bấm; GeoJSON lạ có thể chèn HTML. | Dựng DOM bằng `textContent`/thuộc tính, không nối chuỗi HTML. |
| 8 | Quét tuần tự từng mục tiêu. | 50 mục tiêu phải chờ lâu. | Chạy song song có giới hạn (mặc định 4), tự thử lại khi gặp 429/5xx, có bộ đệm kết quả đo mây theo cảnh. |
| 9 | Nhập GeoJSON: tên luôn có hậu tố “(1)”, bán kính chỉ tính theo vĩ độ, bỏ qua `MultiPoint`/`LineString`. | Tên file kiểu Image Hunter (`DIABAN_LOAI_..._Ten.geojson`) bị thêm “(1)”. | File chỉ có 1 đối tượng thì lấy đúng tên file. Hỗ trợ mọi kiểu hình học, thêm KML (Google Earth) và CSV. |
| 10 | Không có bản đồ, không có lịch sử, không biết khi nào vệ tinh bay qua. | Không trả lời được “hôm nay có ảnh không, mấy giờ có”. | Có bản đồ, dải thời gian các lượt chụp, dự báo lượt bay và dò trước kho Copernicus. |

## 2. Kết quả thử API

### 2.1 Planetary Computer STAC (`/api/stac/v1/search`)
- `GET` trả header `access-control-allow-origin: *`, nên gọi được từ `file://` (origin `null`) và từ `localhost`.
- `POST` + JSON: preflight `OPTIONS` bị trả **405**, nên trình duyệt chặn. POST với `text/plain` thì trả 500.
- Tham số `fields=id,geometry,properties.datetime,...,-assets,-links` giữ phản hồi rất nhỏ (không kèm danh sách asset).
- Mỗi lượt bay thường trả **2–4 item** cho cùng một thời điểm, do các ô MGRS chồng lên nhau (ví dụ 48PYT và 48PYS ở Long Thành). Cần gộp theo `platform + datetime` và chọn ô chứa tâm mục tiêu.

### 2.2 Planetary Computer Data API (TiTiler)
| Endpoint | Kết quả |
|---|---|
| `/item/bbox/{minx},{miny},{maxx},{maxy}.png?...&assets=visual&asset_bidx=visual\|1,2,3&nodata=0` | 200, ảnh màu thật đã cắt đúng khung |
| `...jpg` với `max_size=2048` | 200, khoảng 130 KB cho khung 7 km |
| `...tif` | 200, `image/tiff; application=geotiff`, khoảng 2 MB, có tọa độ |
| `...png?assets=SCL&max_size=160` | 200, PNG xám + alpha, **giá trị pixel = lớp SCL gốc** (3 bóng mây, 8/9 mây, 10 mây ti, 0 hoặc alpha 0 = không có dữ liệu) |
| `assets=B08&assets=B04&assets=B03&rescale=1000,4000` | Hồng ngoại màu giả |
| `assets=B12&assets=B8A&assets=B04&rescale=1000,4000` | SWIR |
| `expression=(B08-B04)/(B08+B04)&asset_as_band=True&colormap_name=rdylgn` | NDVI (phải có `asset_as_band=True`, cú pháp `B08_b1` báo lỗi) |
| `/item/crop/...` | 404 (không dùng) |
| `/item/preview.png` với `HEAD` | 405 |

Vì PNG của lớp SCL mang giá trị thô, trình duyệt có thể tự đếm pixel mây bằng `canvas` mà không cần máy chủ riêng.

### 2.3 Độ trễ dữ liệu (lượt bay 22/09/2026, 03:52 UTC = 10:52 giờ VN)
| Nguồn | Có dữ liệu lúc (UTC) | Trễ | CORS |
|---|---|---|---|
| Copernicus Data Space, L1C | 08:32 | ~4 h 40 | `*`, có trả lời preflight |
| Copernicus Data Space, L2A | 09:29 | ~5 h 40 | `*` |
| Earth Search (AWS), L2A | 09:41–09:50 | ~6 h | `*` |
| Planetary Computer, L2A | có (không ghi `created`) | ~5–7 h | `*` với GET |

Kết luận: ở Việt Nam, ảnh “hôm nay” chỉ có sau khoảng **15:30–18:00 giờ VN**. Nếu trước giờ đó hệ thống báo “chưa có ảnh hôm nay” thì đó là bình thường. Copernicus thường có L1C sớm hơn khoảng 1 giờ. Bản mới dò kho này và báo “Đã chụp, chờ PC”.

### 2.4 Lịch bay
- Lượt bay qua Việt Nam rơi vào khoảng **10:00–11:10 giờ VN** (03:00–04:10 UTC).
- Mỗi vệ tinh lặp lại quỹ đạo tương đối sau đúng **10 ngày**. Hiện có S2A (chiến dịch kéo dài, lệch pha), S2B và S2C. Ví dụ tại Long Thành: S2B 03/09 và 13/09, S2C 08/09 và 18/09, tức một lượt mỗi 5 ngày trên quỹ đạo R075, cộng thêm lượt của S2A.
- Vì vậy chỉ cần lấy lượt chụp gần nhất của mỗi cặp (vệ tinh, quỹ đạo) rồi cộng bội số của 10 ngày là dự báo được ngày bay kế tiếp, không cần tải dữ liệu quỹ đạo (TLE).

### 2.5 Nguồn tải band gốc
- **L1C**: kho công khai Google Cloud `gcp-public-data-sentinel-2`.
  - Lưu theo đường dẫn `tiles/<UTM>/<băng vĩ độ>/<ô>/<SAFE>/GRANULE/<...>/IMG_DATA/*.jp2`.
  - Tải qua HTTPS không cần tài khoản; API liệt kê file có CORS `*`.
  - Ví dụ ô 48QYJ ngày 21/09/2026: 14 file JP2 (B01…B12, B8A, TCI), tổng khoảng 683 MB. Band 10 m mỗi file khoảng 90 MB.
- CDSE cũng có L1C, nhưng link `https` cần đăng nhập OIDC. Earth Search `sentinel-2-l1c` trỏ về bucket S3 kiểu người tải trả phí. Vì vậy bản mới dùng Google Cloud.
- **L2A theo band, cắt vùng**: dùng `/item/bbox/...tif?assets=Bxx&max_size=<số pixel gốc>`. Đã kiểm tra:
  - Khung 20 km, band B11 (20 m) → 1002 px.
  - Khung 20 km, ảnh màu 10 m → 2002 px.
  - Không bị nội suy.
- **Giới hạn khung cắt**: JPG 50 km (~5000 px) trả về sau 7 giây. GeoTIFF 50 km (~66 MB) có lúc bị ngắt giữa chừng, nên khung lớn nhất trong app là 40 km.
- **Xem trọn cảnh**: tile `/item/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?...` được dùng làm lớp phủ Leaflet.

### 2.6 Kho ảnh theo mục tiêu
- Trình duyệt không cho trang web tự chọn thư mục con trong Downloads. Muốn xếp ảnh theo mục tiêu thì phải dùng **File System Access API** (`showDirectoryPicker`, chỉ có trên Chrome/Edge).
- Người dùng chọn thư mục kho một lần. Quyền truy cập thư mục được lưu trong IndexedDB; mỗi phiên mới trình duyệt hỏi lại một lần ngay khi bấm tải.
- Tên thư mục mục tiêu dùng dạng không dấu, giống tên file. Lúc thử, tên có dấu (“Vịnh Hạ Long”) làm file bị ghi nhầm ra thư mục gốc của kho.
- Band L1C được ghi dạng luồng qua đường JSON API của Google Cloud (`storage/v1/b/<bucket>/o/<tên đã mã hóa>?alt=media`, có CORS). Đường tải trực tiếp của file không có CORS nên trình duyệt không đọc được nội dung để ghi vào kho.
  - Trong môi trường thử nghiệm, Chromium nhận 404 ở đường này, trong khi gọi bằng công cụ khác thì được 200; chưa kiểm chứng được trên máy thật.
  - Vì vậy nếu ghi thất bại, app tự chuyển sang tải thường vào thư mục Downloads.

### 2.7 Kho ảnh chung cố định (D:\KHO_ANH\TD)
- Trình duyệt **không cho** trang web ghi vào một đường dẫn cố định mà không có người bấm chọn (kể cả File System Access API). Vì vậy dùng máy chủ cục bộ `server.py` (chỉ thư viện chuẩn Python), do `run.bat` khởi động.
- API: `GET /api/health`, `GET /api/list`, `GET /api/file?path=`, `POST /api/save?folder=&sub=&name=` (gửi dữ liệu), `POST /api/fetch` `{folder, sub, name, url}` (máy chủ tự tải).
- Bảo vệ:
  - Chỉ nghe `127.0.0.1`, chỉ nhận Host là `localhost`/`127.0.0.1`.
  - Lệnh ghi phải có header `X-S2M: 1`. Trang web khác không gửi được header này tới đây mà không qua kiểm tra CORS, và máy chủ không cho phép.
  - Tên thư mục/tệp được làm sạch (không `..`, không ký tự cấm).
  - Chỉ tải từ Planetary Computer, Google Cloud Storage và Azure Blob.
  - Ghi vào tệp `.part` trước rồi mới đổi tên.
- Tải TCI L1C phía máy chủ không vướng CORS, nên tránh được lỗi 404 khi trình duyệt gọi JSON API của Google Cloud (mục 2.6). Đã thử: TCI 48QYJ ngày 21/09 (120 MB) ghi đủ vào kho.

## 3. Thiết kế bản mới

### 3.1 Nguyên tắc
- Vẫn là **một file HTML**, bấm đúp là chạy, không cần máy chủ riêng. Thư viện Leaflet và JSZip lấy từ cdnjs. Nếu CDN lỗi, app vẫn chạy, chỉ mất bản đồ và nút tải ZIP.
- Mọi dữ liệu nằm trong localStorage của máy. Chỉ khung tọa độ mục tiêu được gửi đến API công khai.

### 3.2 Luồng quét cho mỗi mục tiêu
1. `GET /search` với bbox mục tiêu, khoảng `lookback` ngày (mặc định 30), sắp xếp mới nhất trước.
2. Gộp item thành **lượt chụp** (`platform|YYYY-MM-DDTHH:MM`). Trong mỗi lượt, ưu tiên ô chứa tâm mục tiêu, sau đó đến ô ít mây hơn.
3. Với N lượt mới nhất (mặc định 6), tải PNG của lớp SCL cỡ 160 px và đếm tỷ lệ **mây, bóng mây, độ phủ** trong khung. Nếu ô đầu phủ dưới 95%, thử ô tiếp theo. Kết quả được đệm theo `itemId|bbox`, nên lần quét sau chỉ đo các cảnh mới.
4. Dự báo 4 ngày bay kế tiếp.
5. Nếu hôm nay có lượt bay dự kiến mà Planetary Computer chưa có ảnh, hỏi Copernicus (L1C/L2A) trong ngày hôm nay theo giờ VN.
6. So với lần quét trước: có lượt mới thì hiện thông báo trong app, đổi tiêu đề tab và gửi thông báo hệ thống nếu người dùng đã bật.

### 3.3 Giao diện
- **Thanh trên**: Quét tất cả (có tiến trình), Tải ZIP ảnh mới (ảnh JPG đã cắt của mọi mục tiêu kèm `danh_sach.csv`), Cài đặt.
- **Ô tổng hợp** (bấm để lọc): Có ảnh hôm nay, Hôm nay & rõ, Dự kiến bay hôm nay, Đã chụp chờ PC, Lỗi/chưa quét. Kèm một câu tóm tắt tùy theo giờ trong ngày.
- **Danh sách mục tiêu**: ảnh thu nhỏ đã cắt, thời điểm chụp, ngày bay dự kiến, trạng thái và % mây trong vùng. Có tìm kiếm và 4 kiểu sắp xếp.
- **Chi tiết mục tiêu**:
  - Ảnh lớn, chuyển được giữa Màu thật, Hồng ngoại, SWIR và NDVI.
  - Chọn **khung nhìn**: vùng mục tiêu, ×2, ×4, 10, 20 hoặc 40 km. Viền vàng đánh dấu ô mục tiêu.
  - **So sánh hai ngày** bằng thanh trượt.
  - Tải JPG hoặc GeoTIFF ở độ phân giải gốc 10 m theo khung nhìn.
  - Tick chọn nhiều ảnh (nhiều ngày, nhiều mục tiêu) rồi bấm **Tải TCI**: TCI L1C gốc cả ô (JP2) hoặc TCI cắt theo khung nhìn. Theo yêu cầu người dùng, bỏ hộp liệt kê 14 band vì chỉ dùng TCI.
  - Tải cả ô gốc (ký SAS lúc bấm).
  - Bản đồ Leaflet (nền Esri/OSM) có lớp **toàn bộ cảnh 110 km**; có thể bấm lên bản đồ để thêm mục tiêu.
  - Thông tin cảnh: giờ VN, vệ tinh, quỹ đạo, ô MGRS, mây trong vùng và mây cả ô, độ phủ. Có liên kết tới “Ảnh rõ gần nhất”.
  - Dải thời gian mọi lượt chụp trong kỳ. Bấm vào lượt chưa đo thì app đo mây ngay. Phím ←/→ để chuyển lượt.
- **Quản lý mục tiêu**:
  - Thêm bằng tọa độ.
  - Nhập hàng loạt GeoJSON, KML hoặc CSV (kéo thả nhiều file hoặc dán nội dung).
  - Sửa trực tiếp trong bảng.
  - Xuất GeoJSON, sao lưu JSON.
  - Tự chuyển danh sách từ bản cũ nếu còn trong trình duyệt.
- **Cài đặt**: số ngày tìm lại, ngưỡng “rõ”, số lượt đo mây, mức song song, cỡ ảnh tải, tự quét lại mỗi X phút, dò Copernicus, thông báo, giao diện sáng/tối.

### 3.4 Tên file tải về
`<Ten_khong_dau>_<YYYYMMDD>_<HHMM>VN_<S2A|S2B|S2C>_<tc|nir|swir|ndvi>.<jpg|tif>`, ví dụ `Vinh_Ha_Long_20260921_1015VN_S2C_tc.tif`.

## 4. Kiểm thử đã chạy
Chạy bằng Chromium headless, mở từ `file://`, với dữ liệu thật:
- Quét 10 mục tiêu mặc định trong khoảng 24–36 giây. Không mục tiêu nào lỗi; mỗi mục tiêu có 6–8 lượt chụp trong 30 ngày.
- Đo mây trong vùng: Hạ Long 21/09 được 0,3% (ô 1,7%). Dầu Tiếng 21/09 được 97,2% (ô 85,4%).
- Dự báo: 8/10 mục tiêu có lượt bay ngày 23/09. Kết quả khớp với chu kỳ S2B (13/09 + 10 ngày).
- Các kiểu hiển thị Hồng ngoại, SWIR, NDVI và so sánh hai ngày đều hiện đúng. Tải GeoTIFF ra đúng tên file.
- Ở khung 390 px: không có thanh cuộn ngang, bố cục chuyển thành một cột.

## 5. Hướng phát triển tiếp
- Thêm nguồn **Sentinel-1 SAR** (không bị mây che) cho những ngày mục tiêu toàn mây. Planetary Computer có `sentinel-1-rtc`.
- Thêm **Landsat 8/9** (`landsat-c2-l2`) để tăng số lượt quan sát; độ phân giải 30 m.
- Phát hiện thay đổi tự động: so sánh NDVI hoặc độ sáng giữa hai lượt rõ và tô màu vùng thay đổi.
- Chạy quét định kỳ phía máy chủ (Python/cron) và gửi Telegram khi có ảnh mới, để không phải mở trình duyệt.
