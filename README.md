# ITS — TrafficVision AI

Ứng dụng phân tích video giao thông chạy cục bộ: tải video, nhận diện phương tiện, theo dõi, đếm qua vạch, đo tốc độ bằng hai mốc, đánh giá mật độ/ùn tắc và xuất CSV/video.

## Chạy trên Windows

Mở PowerShell tại thư mục dự án:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Nếu môi trường hiện tại đã cài thư viện, chỉ cần `python run.py`. Trên máy hiện tại, trình chạy tự chọn `.venv-gpu` đã kiểm chứng với RTX 3060 khi có dấu `gpu-ready`. Có thể chạy trực tiếp `.\.venv-gpu\Scripts\python.exe run.py`. Mở http://127.0.0.1:8000. Tài liệu API: http://127.0.0.1:8000/docs. Dùng `python run.py --port 8001` nếu cổng 8000 đã được sử dụng. Chế độ phát triển: `python run.py --reload`.

Đã kiểm tra trên Windows với Python 3.14, FastAPI 0.136.3, Pydantic 2.13.4, SQLAlchemy 2.0.51, OpenCV 5.0.0.93 và PyTorch 2.13.0. Tệp mô hình `yolov8n.pt` nằm tại gốc dự án; nếu thiếu, Ultralytics cần tải mô hình. GPU CUDA là tùy chọn.

Gói `imageio-ffmpeg` trong `requirements.txt` cung cấp FFmpeg để mã hóa H.264 phát được trong trình duyệt. Nếu bỏ gói này, ứng dụng tìm `ffmpeg` trong PATH; khi hoàn toàn thiếu FFmpeg, video kết quả có thể chỉ tải về được. Video xuất không chứa âm thanh.

## Dùng thử

1. Tải video lên tại **Phân tích video**, hoặc chọn nút video mẫu.
2. Hệ thống tự đặt ROI/vạch theo chuyển động và bắt đầu phân tích, không cần vẽ hay bấm nút chạy. Khi AI gửi các frame đầu, video và hộp nhận diện phát cùng nhau. Có thể tua trong đoạn đã xử lý; nếu tua xa hơn, trình phát tự đưa về frame có kết quả gần nhất.
3. Khi hoàn tất, xem video hoặc tải CSV/video; xem lại phiên tại **Lịch sử phân tích**.

Video mẫu có 4 ô tô, 1 xe máy, 1 xe tải dạng hình khối. Chế độ Demo dùng bộ dò màu riêng; mặc định không tự giả định khoảng cách thực để đo km/h. Đây không phải tập dữ liệu đánh giá chất lượng nhận diện giao thông thực tế. Video tải lên mặc định dùng YOLO, không tự thay bằng dò hình khối khi YOLO không tìm thấy xe.

## Phân tích video thật

- Tải MP4, AVI, MOV hoặc MKV tối đa 500 MB có FPS hợp lệ.
- Sau khi tải lên, hệ thống lấy mẫu tối đa 16 cặp khung hình để tìm chuyển động, đặt ROI và vạch đếm vuông góc với hướng chuyển động chủ đạo (ngang/dọc). Nếu không thấy chuyển động rõ, dùng vùng quan sát rộng và vạch giữa khung hình. Đây là thiết lập tự động theo chuyển động, không phải nhận dạng chính xác ranh giới làn đường.
- Mở **Nâng cao: xem / chỉnh vùng quan sát và các vạch** nếu muốn sửa. ROI: bấm các đỉnh. Vạch: kéo hoặc bấm hai điểm. Hỗ trợ chuột và cảm ứng. Các vạch A/B cũng được gợi ý sẵn, nhưng chức năng km/h mặc định tắt vì chưa biết khoảng cách thực.
- Bật đếm qua vạch khi đã vẽ vạch. Mỗi ID chỉ được đếm một lần; tổng từng loại bằng tổng xe đã qua vạch. Khi tắt đếm qua vạch, thống kê là số ID đã phát hiện toàn video.
- Bật đo tốc độ khi đã vẽ đủ hai vạch tách biệt và nhập khoảng cách thực theo mặt đường. Công thức: `km/h = 3.6 × mét / giây`; thời gian lấy từ khung hình video, có nội suy điểm cắt. Không đủ hai lần cắt thì tốc độ để trống.
- ROI dùng cho mật độ và tình trạng giao thông. Thẻ tốc độ trung bình phiên dùng tất cả phép đo hợp lệ; biểu đồ tốc độ dùng xe đang trong ROI. Trạng thái cuối là trạng thái gần cuối video, không phải trạng thái nghiêm trọng nhất toàn phiên.
- Ngưỡng trạng thái phải duy trì liên tục đủ số giây cấu hình. Thiếu tốc độ chỉ phân loại theo mật độ, không kết luận ùn tắc bằng tốc độ giả.
- Chọn loại xe, độ tin cậy và ngưỡng tại **Cài đặt**. Nút lưu giữ cài đặt trong trình duyệt. Preset camera lưu ROI, vạch, khoảng cách thực và các lựa chọn bật/tắt.

CSV chứa toàn bộ track cùng cột đã qua vạch và thời điểm qua vạch; bảng giao diện hiển thị 100 bản ghi gần nhất. Tốc độ là ước lượng theo hiệu chỉnh, chưa được đối chứng với thiết bị đo thực. Tracker hiện dùng ghép IoU và dự đoán vận tốc từ các lần quan sát gần nhất; che khuất, camera rung hoặc xe dịch chuyển nhanh giữa hai khung có thể làm đổi ID. Tham số API `frame_skip` từ 1–10 chỉ giảm số lần suy luận; mọi khung nguồn vẫn được ghi vào video, với hộp dự đoán giữa các lần nhận diện. Phép đo tốc độ và đếm chỉ dùng các lần quan sát thật. Tăng giá trị này có thể giảm độ ổn định tracking.

## Dữ liệu và vận hành

SQLite: `trafficvision.db`; video đầu vào: `uploads/`; báo cáo/video: `outputs/`. Có thể đổi vị trí qua `$env:ITS_DATA_DIR='D:\ITS-data'` trước khi chạy. Biểu đồ dùng Chart.js 4.4.1 đi kèm giấy phép MIT trong `frontend/js/vendor/`; font Google tùy chọn có font hệ thống thay thế.

Ứng dụng hiện dành cho máy cá nhân, một tiến trình Uvicorn. Chưa có tài khoản/phân quyền hay hàng đợi xử lý phân tán. Phiên đang xử lý khi máy chủ dừng sẽ được đánh dấu thất bại khi khởi động lại; dùng Chạy lại để tạo phiên mới. Phiên hủy dừng bộ mã hóa và xóa video chưa hoàn tất.

## Kiểm tra

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m playwright install chromium
python scripts/smoke_browser.py
node scripts/test_canvas_editor.cjs
```

Kiểm thử tích hợp dùng SQLite và video trong thư mục tạm, không sửa dữ liệu làm việc. Kiểm thử trình duyệt khởi chạy máy chủ riêng, chặn kết nối ngoài để kiểm tra biểu đồ offline, WebSocket, phát H.264, tải CSV, lưu cài đặt và preset, thao tác vẽ, và luồng chỉ tải video lên rồi tự phân tích bằng YOLO. Ảnh xác minh được lưu vào `outputs/verification_dashboard.png` và `outputs/verification_mobile.png`.

## Cấu trúc

- `backend/app/api/`: video, phiên phân tích, cấu hình camera, xuất báo cáo.
- `backend/app/core/`: nhận diện, tracker, đếm xe, tốc độ, ùn tắc và xử lý video.
- `frontend/`: giao diện HTML/CSS/JavaScript.
- `sample_generator.py`: tạo video mô phỏng độc lập.
- `backend/tests/`: kiểm thử tính toán và API tích hợp.
- `scripts/smoke_browser.py`: kiểm tra thực tế qua Chromium.

## FPS, GPU và nhận diện xe máy

- Mặc định xuất 60 FPS, giữ FPS cao hơn của video nguồn tới 240 FPS. Với nguồn 15/30 FPS, FFmpeg lặp khung để đạt nhịp xuất 60 FPS; không tạo thêm chuyển động thật. Muốn chuyển động gốc 60/120 FPS, cần video được quay ở nhịp đó.
- Trong lúc AI chạy, trình duyệt phát video gốc với hộp nhận diện trên lớp Canvas, khớp theo số frame qua WebSocket. Máy chủ gửi lại các frame gần nhất khi trình duyệt kết nối muộn. Video tạm dừng nếu AI chưa kịp xử lý tới vị trí phát và tiếp tục khi có kết quả. Khi hoàn tất, trình phát chuyển sang video H.264 đã gắn kết quả AI.
- Video tải lên dùng H.264 trong MP4/MKV có thể phát trực tiếp nếu trình duyệt hỗ trợ. Với codec/container không tương thích, trình duyệt gọi `/api/videos/{id}/preview` để đổi sang MP4 H.264; AI vẫn xử lý trong lúc chuẩn bị bản phát. Video mẫu mới được tạo trực tiếp bằng H.264.
- GPU dùng FP16 với YOLOv8s đã tải sẵn, ảnh suy luận 640 px; CPU dùng YOLOv8n 640 px. Có thể chỉ định tệp mô hình bằng biến `ITS_YOLO_MODEL`. Xe máy (COCO class 3) bật mặc định, ngưỡng riêng 0.20; ngưỡng các loại xe khác vẫn theo cài đặt. Giảm ngưỡng có thể tăng phát hiện nhầm; số phát hiện không phải chứng nhận độ chính xác.
- Video được mã hóa H.264 trực tiếp bằng NVENC khi phép kiểm tra phần cứng thành công; nếu không có NVENC phù hợp thì dùng libx264. ITS ưu tiên FFmpeg 7.1 đóng gói trong `imageio-ffmpeg` để tương thích driver hiện tại, bỏ bước ghi MP4 rồi mã hóa lần hai. Cạnh dài video kết quả tối đa 1280 px để giảm tải phát/ghi; suy luận và tính toán tọa độ vẫn dựa trên ảnh đầu vào. Không thay đổi tốc độ chạy hoặc độ dài video.
- `processing_fps` là số khung nguồn xử lý mỗi giây, khác FPS phát và FPS suy luận. Mỗi phép đo phụ thuộc độ phân giải, mật độ xe, GPU và tác vụ đang chạy.

Môi trường GPU tại máy này dùng PyTorch 2.13.0+cu126 và torchvision 0.28.0+cu126 từ [kho chính thức PyTorch](https://pytorch.org/get-started/previous-versions/), nằm riêng trong `.venv-gpu` và kế thừa thư viện của Python đã cài. Không thay đổi bản PyTorch CPU toàn máy. Để thiết lập lại trên cùng Python:

```powershell
python -m venv --system-site-packages .venv-gpu
.\.venv-gpu\Scripts\python.exe -m pip install torch==2.13.0+cu126 torchvision==0.28.0+cu126 --index-url https://download.pytorch.org/whl/cu126
.\.venv-gpu\Scripts\python.exe -m pip install imageio-ffmpeg==0.6.0
.\.venv-gpu\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"
.\.venv-gpu\Scripts\python.exe run.py
```

Đo hiệu năng: `.\.venv-gpu\Scripts\python.exe scripts/benchmark_detector.py` đo suy luận trên khung mẫu, và `scripts/benchmark_pipeline.py` đo cả phân tích/xuất video trên 300 khung lấy từ video tải gần nhất. Phép đo thứ hai dùng SQLite/video tạm và ghi báo cáo `outputs/performance_report.json`.

Lần đo gần nhất trên máy RTX 3060, video 768×432, nguồn 14.985 FPS: 300 khung xử lý trong 3.72 giây (~80.7 khung nguồn/giây), xuất 1201 khung ở 60 FPS bằng NVENC. Đoạn này đếm 13 track xe máy qua vạch. Tốc độ thay đổi theo tải máy và video; đây là phép đo hiệu năng/đầu ra, chưa phải đánh giá precision/recall với dữ liệu gán nhãn. Báo cáo mới sẽ ghi đè số liệu khi chạy lại benchmark.
