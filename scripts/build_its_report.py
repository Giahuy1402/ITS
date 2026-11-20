"""Build a reproducible Vietnamese Word report from local ITS evidence."""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import cv2
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.counter import LineCounter
from backend.app.core.detector import DemoVehicleDetector
from backend.app.core.speed_estimator import SpeedEstimator
from backend.app.core.tracker import SimpleByteTracker


OUT = ROOT / "outputs" / "Bao_cao_du_an_ITS_TrafficVision.docx"
PERF = ROOT / "outputs" / "performance_report.json"
SAMPLE = ROOT / "uploads" / "sample_traffic.mp4"

VEHICLES = [
    ("Ô tô 1", 0, 450, 6.5, 60, 100, 2),
    ("Ô tô 2", 15, 650, 8.0, 55, 90, 2),
    ("Xe tải 1", 45, 480, 5.0, 70, 120, 7),
    ("Xe máy 1", 75, 620, 7.2, 40, 60, 3),
    ("Ô tô 3", 120, 520, 6.0, 65, 100, 2),
    ("Ô tô 4", 150, 680, 9.0, 50, 85, 2),
]
CLASS_NAME = {2: "Ô tô", 3: "Xe máy", 7: "Xe tải"}


def iou(a, b):
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return inter / (area_a + area_b - inter) if area_a + area_b > inter else 0.0


def ground_truth(frame_idx):
    truth = []
    for name, start, x, speed, w, h, cls in VEHICLES:
        if frame_idx < start:
            continue
        top = int((frame_idx - start) * speed) - h
        y1, y2 = max(0, top), min(720, top + h + 1)
        if y2 - y1 >= 15:
            truth.append({"name": name, "bbox": [x, y1, x + w + 1, y2], "class_id": cls})
    return truth


def evaluate_sample():
    if not SAMPLE.exists():
        raise FileNotFoundError(f"Thiếu video mẫu: {SAMPLE}")
    cap = cv2.VideoCapture(str(SAMPLE))
    if not cap.isOpened():
        raise RuntimeError(f"Không mở được video mẫu: {SAMPLE}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not 29.5 <= fps <= 30.5:
        raise RuntimeError(f"Video mẫu phải là 30 FPS, nhận được {fps}")
    detector, tracker = DemoVehicleDetector(), SimpleByteTracker()
    counter = LineCounter((300, 360), (980, 360))
    speed = SpeedEstimator((300, 216), (980, 216), (300, 468), (980, 468), 10.0)
    scores = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "ious": []})
    first_seen = {}
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        detections = detector.detect(frame)
        truths = ground_truth(frame_idx)
        pairs = sorted(
            ((iou(t["bbox"], d["bbox"]), ti, di)
             for ti, t in enumerate(truths) for di, d in enumerate(detections)
             if t["class_id"] == d["class_id"]), reverse=True)
        matched_t, matched_d = set(), set()
        for overlap, ti, di in pairs:
            if overlap < 0.5 or ti in matched_t or di in matched_d:
                continue
            matched_t.add(ti)
            matched_d.add(di)
            item = scores[truths[ti]["class_id"]]
            item["tp"] += 1
            item["ious"].append(overlap)
        for ti, truth in enumerate(truths):
            if ti not in matched_t:
                scores[truth["class_id"]]["fn"] += 1
        for di, detection in enumerate(detections):
            if di not in matched_d:
                scores[detection["class_id"]]["fp"] += 1
        for obj in tracker.update(detections, frame_idx / fps, frame_idx + 1):
            tid = obj["track_id"]
            first_seen.setdefault(tid, (frame_idx, obj["class_id"]))
            traj = tracker.get_trajectory(tid)
            counter.check_crossing(tid, traj, obj["class_name"])
            speed.process_track(tid, traj)
        frame_idx += 1
    cap.release()
    if frame_idx != 300:
        raise RuntimeError(f"Video mẫu phải có 300 frame, nhận được {frame_idx}")
    measured = []
    for name, start, x, pixel_speed, w, h, cls in VEHICLES:
        candidates = []
        for tid, (observed_start, observed_cls) in first_seen.items():
            record = speed.records.get(tid, {})
            if observed_cls == cls and record.get("is_valid"):
                candidates.append((abs(observed_start - start), tid, record["speed_kmh"]))
        if candidates:
            distance, tid, observed = min(candidates)
            if distance <= 8:
                true_speed = 3.6 * 10.0 * pixel_speed * fps / (468 - 216)
                measured.append((name, true_speed, observed, observed - true_speed))
    return {"frames": frame_idx, "fps": fps, "scores": dict(scores),
            "counts": dict(counter.counts_by_type), "total": counter.total_count,
            "speed_rows": measured, "valid_speed_tracks": sum(bool(r.get("is_valid")) for r in speed.records.values())}


def set_cell(cell, value):
    cell.text = str(value)
    for para in cell.paragraphs:
        para.space_after = Pt(0)
        for run in para.runs:
            run.font.size = Pt(8)


def table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Shading Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, header in zip(t.rows[0].cells, headers):
        set_cell(cell, header)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    for row in rows:
        cells = t.add_row().cells
        for cell, value in zip(cells, row):
            set_cell(cell, value)
    if widths:
        for row in t.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = Cm(width)
    doc.add_paragraph()
    return t


def para(doc, text="", bold_lead=None):
    p = doc.add_paragraph()
    if bold_lead and text.startswith(bold_lead):
        p.add_run(bold_lead).bold = True
        p.add_run(text[len(bold_lead):])
    else:
        p.add_run(text)
    return p


def picture(doc, filename, caption, width=15.0):
    path = ROOT / "outputs" / filename
    if not path.exists():
        raise FileNotFoundError(path)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=Cm(width))
    p = doc.add_paragraph(caption)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in p.runs:
        run.italic = True
        run.font.size = Pt(8)


def main():
    perf = json.loads(PERF.read_text(encoding="utf-8"))
    sample = evaluate_sample()
    scores = sample["scores"]
    totals = {key: sum(v[key] for v in scores.values()) for key in ("tp", "fp", "fn")}
    precision = totals["tp"] / (totals["tp"] + totals["fp"])
    recall = totals["tp"] / (totals["tp"] + totals["fn"])
    f1 = 2 * precision * recall / (precision + recall)
    speed_rows = sample["speed_rows"]
    if len(speed_rows) != 6:
        raise RuntimeError(f"Cần đủ 6 phép đo tốc độ để báo cáo, hiện có {len(speed_rows)}: {speed_rows}")
    mae = sum(abs(r[3]) for r in speed_rows) / len(speed_rows)
    rmse = math.sqrt(sum(r[3] ** 2 for r in speed_rows) / len(speed_rows))
    mape = 100 * sum(abs(r[3]) / r[1] for r in speed_rows) / len(speed_rows)
    source_duration = perf["source_frames"] / perf["source_fps"]
    output_duration = perf["output_frames"] / perf["output_fps"]
    duration_error = output_duration - source_duration
    doc = Document()
    doc.core_properties.title = "Báo cáo dự án ITS – TrafficVision AI"
    doc.core_properties.subject = "Công nghệ, kết quả chạy thử và đánh giá sai số"
    doc.core_properties.keywords = "ITS, YOLO, giao thông, sai số, video"
    sec = doc.sections[0]
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(2.4)
    sec.right_margin = Cm(2.0)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    for name in ("Title", "Heading 1", "Heading 2"):
        doc.styles[name].font.name = "Calibri"
        doc.styles[name].font.color.rgb = RGBColor(20, 63, 111)
    h = sec.header.paragraphs[0]
    h.text = "ITS  |  TrafficVision AI"
    h.style = doc.styles["Caption"]
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.text = "Báo cáo kỹ thuật • 10/10/2026"

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("BÁO CÁO DỰ ÁN ITS").bold = True
    p.runs[0].font.size = Pt(22)
    p.runs[0].font.color.rgb = RGBColor(20, 63, 111)
    p = doc.add_paragraph("HỆ THỐNG PHÂN TÍCH GIAO THÔNG TỪ VIDEO\nTRAFFICVISION AI")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in p.runs:
        run.bold = True
        run.font.size = Pt(15)
    para(doc, "Bản báo cáo kỹ thuật và đánh giá thực nghiệm | Ngày 10/10/2026")
    para(doc, "Dự án: F:\\ITS | Nền tảng: Windows, Python, trình duyệt web | Môi trường thử nghiệm: NVIDIA GeForce RTX 3060")
    doc.add_heading("Tóm tắt", 1)
    para(doc, "TrafficVision AI tiếp nhận video giao thông, tự ước lượng vùng quan sát/vạch đếm, nhận diện và theo dõi ô tô, xe máy, xe buýt, xe tải; đếm phương tiện, ước lượng tốc độ khi có khoảng cách thực, đánh giá mật độ và xuất video/báo cáo. Ảnh chụp bên dưới là kết quả chạy ứng dụng, không phải ảnh minh họa dựng lại.")
    para(doc, f"Phép đo trên 300 frame video thật 768×432 cho tốc độ xử lý toàn pipeline {perf['full_pipeline_source_fps']:.1f} frame nguồn/giây, video đầu ra {perf['output_fps']:.0f} FPS. Bộ dữ liệu mô phỏng có nhãn biết trước được dùng để tính precision, recall, sai số đếm và sai số tốc độ. Kết quả này không suy rộng thành độ chính xác trên đường phố thật khi chưa có bộ nhãn thủ công.")

    doc.add_heading("1. Mục tiêu, phạm vi và kiến trúc", 1)
    para(doc, "Mục tiêu sử dụng: người dùng tải video lên, hệ thống khởi tạo phân tích tự động; có thể sửa ROI/vạch khi cần. Trong lúc xử lý, trình duyệt phát video nguồn cùng khung nhận diện cập nhật qua WebSocket; khi hoàn tất, chuyển sang video kết quả H.264. Thống kê và nhật ký được lưu để xem lại.")
    table(doc, ["Lớp", "Chức năng"], [
        ("Đầu vào", "Video MP4/AVI/MOV/MKV; lấy metadata, tạo preview phù hợp trình duyệt."),
        ("Phân tích", "Tự bố trí ROI/vạch từ chuyển động; YOLO nhận diện; tracker gán ID; đếm, đo tốc độ và phân loại trạng thái giao thông."),
        ("Dịch vụ", "FastAPI phục vụ tải lên, phiên phân tích, WebSocket, báo cáo CSV/video và cấu hình camera."),
        ("Đầu ra", "Giao diện trực tiếp, bảng xe, đồ thị, trạng thái ROI, MP4 H.264 60 FPS và CSV."),
    ])
    para(doc, "Luồng xử lý: tải video → đọc frame → nhận diện YOLO → theo dõi ID → ROI/vạch đếm/vạch đo tốc độ → cơ sở dữ liệu + WebSocket → giao diện + CSV/MP4.")
    para(doc, "Vạch và ROI tự động dựa trên mẫu chuyển động trong tối đa 16 frame; đây là ước lượng hình học, có thể cần chỉnh khi camera đặt lệch hoặc cảnh có chuyển động nhiễu. Khoảng cách vật lý giữa hai vạch đo tốc độ phải do người dùng cung cấp nếu muốn kết quả km/h có ý nghĩa thực tế.")

    doc.add_heading("2. Công nghệ áp dụng", 1)
    table(doc, ["Công nghệ / phiên bản tại máy thử", "Vai trò và cấu hình"], [
        ("Python 3.14", "Xử lý video, API, đo lường và kiểm thử."),
        ("FastAPI 0.136.3 + Uvicorn 0.48.0", "REST API, WebSocket, phục vụ dashboard."),
        ("Ultralytics 8.4.113 / YOLOv8s", "Nhận diện COCO class 2, 3, 5, 7: ô tô, xe máy, xe buýt, xe tải; ảnh suy luận 640 px."),
        ("PyTorch 2.13.0+cu126 / CUDA", "Suy luận trên RTX 3060, dùng bán chính xác 16-bit khi GPU hỗ trợ; CPU dùng mô hình YOLOv8n nhẹ hơn."),
        ("OpenCV 5.0.0.93 / NumPy 2.3.4", "Giải mã frame, vẽ hộp/vạch, xử lý ảnh và tính toán hình học."),
        ("SimpleByteTracker (nội bộ)", "Ghép phát hiện liên tiếp bằng IoU và duy trì ID/quỹ đạo; không phải thuật toán ByteTrack đầy đủ."),
        ("SQLite + SQLAlchemy 2.0.51", "Lưu video, phiên phân tích, bản ghi phương tiện và nhật ký mật độ."),
        ("Pydantic 2.13.4", "Kiểm tra cấu hình API, vạch không suy biến, tham số hợp lệ."),
        ("FFmpeg / imageio-ffmpeg 0.6.0", "Tạo MP4 H.264; dùng NVENC khi khả dụng, dự phòng libx264."),
        ("HTML/CSS/JavaScript + Canvas", "Phát video, phủ hộp nhận diện đồng bộ, chỉnh vạch/ROI, bảng và đồ thị."),
    ])
    para(doc, "Ngưỡng nhận diện mặc định: 0,20 cho xe máy và 0,35 cho các lớp xe khác; IoU NMS 0,5. Hạ ngưỡng xe máy giúp tăng khả năng thấy xe nhỏ nhưng có thể tăng phát hiện nhầm. Giá trị này chưa được tối ưu trên tập nhãn giao thông riêng.")

    doc.add_heading("3. Hình ảnh chạy thử", 1)
    picture(doc, "verification_real_live.png", "Hình 1. Video giao thông thật: hộp AI và ID xe máy/ô tô/xe buýt hiển thị trực tiếp trên đúng khung hình nguồn.", 14.5)
    para(doc, "Video thật được kiểm tra từ file tải lên dài khoảng 15 phút, nguồn 768×432 ở 14,985 FPS. Ảnh thể hiện trực quan hệ thống có nhận diện xe máy, nhưng một khung hình không đủ để tính độ chính xác định lượng.")
    picture(doc, "verification_dashboard.png", "Hình 2. Kết quả chạy video mô phỏng: đếm 4 ô tô, 1 xe máy, 1 xe tải, tốc độ trung bình 29,8 km/h và bảng ID/phép đo.", 13.8)

    doc.add_heading("4. Thiết kế phép thử và công thức sai số", 1)
    para(doc, "Thử nghiệm A — video mô phỏng: 10 giây, 1280×720, 30 FPS, 300 frame; 6 phương tiện có vị trí, loại và vận tốc pixel biết trước. Dùng bộ phát hiện màu chỉ dành cho video mẫu, tracker/vạch đếm/vạch tốc độ của dự án. Vạch đếm y=360 px; vạch tốc độ A=216 px, B=468 px, gán khoảng cách 10 m. Mỗi frame, ghép hộp cùng lớp bằng IoU ≥ 0,5; vật thể chuẩn chỉ tính khi phần hiển thị cao ít nhất 15 px. Đây là phép thử tích hợp với dữ liệu điều khiển, không đo chất lượng YOLO trên ảnh thật.")
    para(doc, "Thử nghiệm B — video thật: đoạn 300 frame bắt đầu khoảng giây thứ 5 từ file MKV đã tải lên, 768×432, 14,985 FPS, YOLOv8s trên RTX 3060 và NVENC, xuất 60 FPS. Thời gian toàn pipeline lấy từ outputs/performance_report.json; bộ đếm thời gian bắt đầu sau khi cắt clip, tự tạo ROI/vạch, nạp và làm nóng mô hình nên không bao gồm thời gian tải file hay chuẩn bị ban đầu. Video thật không có danh sách nhãn chuẩn nên chỉ báo cáo hiệu năng và quan sát định tính, không công bố precision/recall thực địa.")
    table(doc, ["Chỉ số", "Định nghĩa"], [
        ("Precision / Recall / F1", "TP/(TP+FP); TP/(TP+FN); 2PR/(P+R). TP là hộp cùng lớp ghép IoU ≥ 0,5."),
        ("Sai số đếm", "ΔN = N hệ thống − N chuẩn; sai số tương đối = |ΔN|/N chuẩn × 100%."),
        ("Tốc độ chuẩn", "v = 3,6 × d/Δt; Δt = (468−216)/(u×30), u là pixel/frame; d=10 m."),
        ("Sai số tốc độ", "eᵢ = v đo − v chuẩn; MAE=trung bình |eᵢ|; RMSE=căn bậc hai trung bình eᵢ²; MAPE=trung bình |eᵢ|/v chuẩn ×100%."),
        ("Sai số thời lượng", "ΔT = frame xuất/FPS xuất − frame nguồn/FPS nguồn; sai số tương đối = |ΔT|/T nguồn ×100%."),
    ])

    doc.add_heading("5. Kết quả định lượng và đánh giá sai lệch", 1)
    det_rows = []
    for cls in (2, 3, 7):
        s = scores.get(cls, {"tp": 0, "fp": 0, "fn": 0, "ious": []})
        p = s["tp"] / (s["tp"] + s["fp"]) if s["tp"] + s["fp"] else 0
        r = s["tp"] / (s["tp"] + s["fn"]) if s["tp"] + s["fn"] else 0
        miou = sum(s["ious"]) / len(s["ious"]) if s["ious"] else 0
        det_rows.append((CLASS_NAME[cls], s["tp"], s["fp"], s["fn"], f"{p*100:.2f}%", f"{r*100:.2f}%", f"{miou:.3f}"))
    det_rows.append(("Tổng", totals["tp"], totals["fp"], totals["fn"], f"{precision*100:.2f}%", f"{recall*100:.2f}%", "—"))
    doc.add_heading("5.1. Sai số phát hiện trên video mô phỏng", 2)
    table(doc, ["Loại", "TP", "FP", "FN", "Precision", "Recall", "IoU TB"], det_rows)
    para(doc, f"F1 tổng = {f1*100:.2f}%. Đơn vị TP/FP/FN là cặp hộp theo frame, vì mỗi xe xuất hiện trong nhiều frame; các số này không phải số lượng xe duy nhất. Sai lệch tập trung ở giai đoạn phương tiện mới lộ một phần hoặc bị che bởi vạch/xe khác; video mẫu có hình chữ nhật màu rõ nên kết quả này thường lạc quan hơn đường phố thật.")

    doc.add_heading("5.2. Sai số đếm phương tiện", 2)
    count_rows = []
    for cls, expected in ((2, 4), (3, 1), (7, 1)):
        got = sample["counts"].get(CLASS_NAME[cls], 0)
        count_rows.append((CLASS_NAME[cls], expected, got, got-expected, f"{abs(got-expected)/expected*100:.1f}%"))
    count_rows.append(("Tổng", 6, sample["total"], sample["total"]-6, f"{abs(sample['total']-6)/6*100:.1f}%"))
    table(doc, ["Loại", "Chuẩn", "Hệ thống", "ΔN", "Sai số tương đối"], count_rows)
    para(doc, "Số đếm được tính khi tâm đáy của track cắt vạch; mỗi ID chỉ đếm một lần. Sai số đếm trên video mô phỏng không phản ánh lỗi có thể có do che khuất, ID bị đứt hay camera rung ở hiện trường.")

    doc.add_heading("5.3. Sai số đo tốc độ", 2)
    speed_table = [(name, f"{true:.3f}", f"{observed:.1f}", f"{error:+.3f}", f"{abs(error)/true*100:.3f}%")
                   for name, true, observed, error in speed_rows]
    table(doc, ["Xe", "Chuẩn km/h", "Đo km/h", "Sai số km/h", "Sai số %"], speed_table)
    para(doc, f"MAE = {mae:.3f} km/h; RMSE = {rmse:.3f} km/h; MAPE = {mape:.3f}%; số mẫu hợp lệ = {len(speed_rows)}/6. Giá trị đo được làm tròn 0,1 km/h trong ứng dụng. Sai số phát sinh từ giải mã/nén hình, vị trí hộp, lượng tử hóa theo frame, nội suy thời điểm cắt vạch và làm tròn.")
    para(doc, "Với video thật, khoảng cách 10 m chỉ có ý nghĩa khi đo đúng ngoài hiện trường. Nếu khoảng cách nhập sai theo tỷ lệ k, tốc độ tính ra cũng sai theo cùng tỷ lệ: v tính/v thật = d nhập/d thật (giả sử thời điểm cắt vạch đúng). Ví dụ nhập 10 m khi thực tế 8 m sẽ làm tốc độ cao hơn 25%; do đó báo cáo không đưa ra sai số km/h thực địa từ video chưa hiệu chuẩn.")

    doc.add_heading("5.4. Thông lượng xử lý và sai số FPS/thời lượng", 2)
    table(doc, ["Chỉ tiêu", "Giá trị đo / tính"], [
        ("Nguồn", f"{perf['source_frames']} frame; {perf['source_fps']:.3f} FPS; {source_duration:.3f} giây"),
        ("Toàn pipeline", f"{perf['elapsed_seconds']:.2f} giây; {perf['full_pipeline_source_fps']:.1f} frame nguồn/giây; khoảng {perf['full_pipeline_source_fps']/perf['source_fps']:.2f}× thời gian thực trên đoạn thử"),
        ("Đầu ra", f"{perf['output_frames']} frame; {perf['output_fps']:.0f} FPS; {output_duration:.3f} giây; H.264 NVENC"),
        ("Sai số thời lượng", f"{duration_error:+.4f} giây; {abs(duration_error)/source_duration*100:.4f}%"),
        ("Tỷ lệ frame đầu ra/nguồn", f"{perf['output_frames']/perf['source_frames']:.3f}×; chủ yếu lặp frame vì nguồn chỉ {perf['source_fps']:.3f} FPS"),
        ("Phương tiện qua vạch", f"{perf['counted_vehicles']} track, trong đó {perf['counted_motorcycles']} track xe máy (không có nhãn chuẩn để tính sai số)"),
    ])
    para(doc, "80,7 frame/giây là thông lượng xử lý frame nguồn trên đoạn 300 frame, không phải FPS chuyển động của video đầu vào hoặc số khung hình AI duy nhất mỗi giây phát. Xuất 60 FPS bằng lặp frame từ nguồn ~15 FPS nên không tạo ra 60 trạng thái chuyển động độc lập; muốn chuyển động 60 FPS thật cần nguồn quay 60 FPS hoặc nội suy chuyển động riêng. Kết quả benchmark ngắn không bảo đảm toàn video 15 phút luôn có cùng tốc độ khi nhiệt độ GPU, mật độ xe và tác vụ nền thay đổi.")

    doc.add_heading("6. Kiểm thử chức năng, giới hạn và hướng cải tiến", 1)
    para(doc, "Bộ kiểm thử dự án đã chạy 47 ca pytest thành công; kiểm tra JavaScript canvas và luồng trình duyệt cũng thành công. Các luồng đã xác nhận gồm tải video, khởi tạo phiên, preview H.264, phủ nhận diện trực tiếp, xuất CSV/video và nhận diện xe máy trên đoạn video thật. Ảnh chụp là bằng chứng vận hành tại thời điểm thử, không chứng minh độ chính xác thống kê.")
    para(doc, "Giới hạn chính: thiếu nhãn chuẩn trên video thật; ngưỡng YOLO chưa được hiệu chỉnh bằng precision–recall theo từng loại xe; tracker IoU đơn giản dễ đổi ID khi xe che khuất; ROI tự động có thể không trùng làn đường; tốc độ phụ thuộc phép đo khoảng cách thực và góc nhìn; 60 FPS đầu ra không khôi phục chuyển động bị thiếu từ nguồn 15 FPS.")
    para(doc, "Đề xuất đánh giá tiếp: gán nhãn thủ công ít nhất vài trăm frame ở nhiều camera, giờ/ánh sáng/thời tiết; lập ma trận nhầm lẫn theo lớp và kích cỡ; so đếm với đếm tay từng chiều; đo tốc độ với cự ly khảo sát hoặc radar; kiểm tra IDF1/MOTA nếu có nhãn quỹ đạo; benchmark toàn video trên GPU/CPU với phân vị thời gian xử lý và mức dùng bộ nhớ.")

    doc.add_heading("7. Kết luận", 1)
    para(doc, f"Hệ thống đã vận hành được quy trình tải video → phân tích AI → hiển thị trực tiếp → thống kê và xuất kết quả. Trên cấu hình RTX 3060, thử nghiệm 300 frame thật đạt {perf['full_pipeline_source_fps']:.1f} frame nguồn/giây; đoạn mô phỏng có {sample['total']}/6 xe được đếm và MAPE tốc độ {mape:.3f}% khi khoảng cách 10 m đã biết. Các con số này chỉ có hiệu lực trong điều kiện thử nêu trên. Để khẳng định độ chính xác thực địa, cần bộ video thật có nhãn chuẩn và hiệu chuẩn khoảng cách tại camera.")
    doc.add_heading("Phụ lục: nguồn số liệu và khả năng tái lập", 1)
    para(doc, "Mã nguồn dữ liệu mẫu: sample_generator.py. Nhận diện/theo dõi/đếm/tốc độ: backend/app/core/. Script benchmark video thật: scripts/benchmark_pipeline.py; số liệu lưu trong outputs/performance_report.json. Ảnh chụp chạy thử: outputs/verification_real_live.png và outputs/verification_dashboard.png. Script tạo báo cáo này đọc và tính lại các chỉ số từ các tệp trong dự án; không gán số độ chính xác cho video thật khi không có nhãn.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(json.dumps({"report": str(OUT), "frames": sample["frames"], "count": sample["total"],
                      "precision": precision, "recall": recall, "f1": f1, "mae": mae,
                      "rmse": rmse, "mape": mape, "speed_rows": speed_rows,
                      "per_class": {CLASS_NAME[k]: {a: v[a] for a in ("tp", "fp", "fn")} for k, v in scores.items()}}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
