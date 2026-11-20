let canvasEditor = null;
let chartsController = null;

let selectedVideo = null; // Video object from API
let activeSessionId = null;
let activeWebSocket = null;
let currentPresetConfig = null;
let pollGeneration = 0;
let preparingVideo = false;
let analysisRunning = false;
let liveOverlayFrames = new Map();
let liveOverlayAnimation = null;
let liveOverlayEnabled = false;
let latestLiveFrame = 0;
let firstLiveFrame = 0;
let livePlaybackWaiting = false;
let liveSeekTarget = null;
let lastRenderedFrame = 0;
let lastRenderedTracks = null;

function utcDate(value) {
    return new Date(/[Zz]|[+-]\d\d:\d\d$/.test(value) ? value : value + "Z");
}

function escapeHtml(value) {
    const element = document.createElement("span");
    element.textContent = String(value ?? "");
    return element.innerHTML;
}

const settingIds = ["setting-conf", "setting-occupancy", "setting-slow-speed", "setting-slow-ratio", "setting-duration"];
function restoreSystemSettings() {
    try {
        const saved = JSON.parse(localStorage.getItem("its-settings") || "null");
        if (!saved) return;
        if (!saved.vehicle_defaults_v2) {
            saved.classes = [...new Set([...(saved.classes || [2, 5, 7]), 3])];
            saved.vehicle_defaults_v2 = true;
            localStorage.setItem("its-settings", JSON.stringify(saved));
        }
        settingIds.forEach(id => { if (saved[id] !== undefined) document.getElementById(id).value = saved[id]; });
        document.querySelectorAll(".setting-cls").forEach(el => { el.checked = saved.classes.includes(Number(el.value)); });
        document.getElementById("val-conf").innerText = document.getElementById("setting-conf").value;
    } catch (error) { console.warn("Không thể khôi phục cài đặt", error); }
}

function resetResults() {
    pollGeneration++;
    if (activeWebSocket) activeWebSocket.close();
    const player = document.getElementById("output-video-player");
    player.pause();
    player.removeAttribute("src");
    player.load();
    player.style.display = "none";
    resetLiveOverlay();
    document.getElementById("video-placeholder").style.display = "block";
    document.getElementById("video-placeholder").textContent = "Đang chờ khung hình phân tích...";
    ["btn-download-csv", "btn-download-video"].forEach(id => {
        const el = document.getElementById(id);
        el.removeAttribute("href");
        el.style.display = "none";
    });
    ["count-car", "count-moto", "count-bus", "count-truck"].forEach(id => document.getElementById(id).innerText = "0");
    document.getElementById("progress-bar-fill").style.width = "0%";
    document.getElementById("progress-pct-text").innerText = "0%";
    document.getElementById("avg-speed-text").innerHTML = "-- <small>km/h</small>";
    updateVehicleTable([]);
    chartsController.reset();
}

function resetLiveOverlay() {
    liveOverlayFrames.clear();
    latestLiveFrame = 0;
    firstLiveFrame = 0;
    livePlaybackWaiting = false;
    liveSeekTarget = null;
    lastRenderedFrame = 0;
    lastRenderedTracks = null;
    liveOverlayEnabled = false;
    if (liveOverlayAnimation) cancelAnimationFrame(liveOverlayAnimation);
    liveOverlayAnimation = null;
    const canvas = document.getElementById("live-overlay-canvas");
    const player = document.getElementById("output-video-player");
    if (player) {
        player.onloadedmetadata = null;
        player.ontimeupdate = null;
        player.onseeking = null;
        player.onseeked = null;
        player.onerror = null;
    }
    const stage = document.querySelector(".video-stage");
    if (stage) stage.style.display = "none";
    if (canvas) {
        canvas.style.display = "none";
        canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    }
}

function colorForVehicle(className) {
    if (className === "Xe máy") return "#00c8ff";
    if (className === "Xe buýt") return "#ff8a00";
    if (className === "Xe tải") return "#ff4d4f";
    return "#35e28a";
}

function renderLiveOverlay() {
    liveOverlayAnimation = null;
    const player = document.getElementById("output-video-player");
    const canvas = document.getElementById("live-overlay-canvas");
    if (!liveOverlayEnabled || !selectedVideo || !canvas) return;
    if (!player.videoWidth || !player.videoHeight) {
        liveOverlayAnimation = requestAnimationFrame(renderLiveOverlay);
        return;
    }

    // The stage, video and canvas share one aspect ratio. This avoids layout
    // measurements on every animation frame and removes browser letterboxing.
    if (canvas.width !== selectedVideo.width || canvas.height !== selectedVideo.height) {
        canvas.width = selectedVideo.width;
        canvas.height = selectedVideo.height;
        lastRenderedFrame = 0;
    }
    const context = canvas.getContext("2d");
    const currentFrame = currentSourceFrame(player);
    // Frame timestamps can differ slightly between OpenCV and the browser.
    // Higher-FPS sources also send at most 60 overlay updates per second.
    let tracks = liveOverlayFrames.get(currentFrame);
    if (tracks === undefined) {
        const maxGap = Math.max(2, Math.ceil(selectedVideo.fps / 60) + 1);
        for (let gap = 1; gap <= maxGap && tracks === undefined; gap++) {
            tracks = liveOverlayFrames.get(currentFrame - gap)
                ?? liveOverlayFrames.get(currentFrame + gap);
        }
    }
    if (currentFrame !== lastRenderedFrame || tracks !== lastRenderedTracks) {
        context.clearRect(0, 0, canvas.width, canvas.height);
        lastRenderedFrame = currentFrame;
        lastRenderedTracks = tracks;
        if (tracks) {
            context.lineWidth = Math.max(2, canvas.width / 640 * 2);
            context.font = `${Math.max(14, canvas.width / 640 * 15)}px Arial`;
            context.textBaseline = "top";
            for (const track of tracks) {
                const [x1, y1, x2, y2] = track.bbox;
                const color = colorForVehicle(track.class_name);
                const speedLabel = (track.speed_kmh !== null && track.speed_kmh !== undefined) ? ` · ${track.speed_kmh} km/h` : "";
                const label = `#${track.track_id} ${track.class_name}${speedLabel}`;
                context.strokeStyle = color;
                context.fillStyle = color;
                context.strokeRect(x1, y1, Math.max(1, x2 - x1), Math.max(1, y2 - y1));
                const labelWidth = context.measureText(label).width + 8;
                const labelY = Math.max(0, y1 - 20);
                context.fillRect(x1, labelY, labelWidth, 20);
                context.fillStyle = "#07111f";
                context.fillText(label, x1 + 4, labelY + 2);
            }
        }
    }
    liveOverlayAnimation = requestAnimationFrame(renderLiveOverlay);
}

function startLiveOverlay() {
    const canvas = document.getElementById("live-overlay-canvas");
    if (!canvas) return;
    liveOverlayEnabled = true;
    canvas.style.display = "block";
    if (!liveOverlayAnimation) liveOverlayAnimation = requestAnimationFrame(renderLiveOverlay);
}

function currentSourceFrame(player) {
    return Math.max(1, Math.floor(player.currentTime * selectedVideo.fps) + 1);
}

function syncLivePlayback() {
    const player = document.getElementById("output-video-player");
    if (!liveOverlayEnabled || !selectedVideo || !player.videoWidth || player.seeking) return;
    const frameNumber = currentSourceFrame(player);
    if (latestLiveFrame < frameNumber + 2) {
        if (!player.paused) livePlaybackWaiting = true;
        player.pause();
    } else if (livePlaybackWaiting && !player.ended) {
        livePlaybackWaiting = false;
        player.play().catch(() => {});
    }
}

function clampLiveSeek() {
    if (!liveOverlayEnabled || !selectedVideo || !latestLiveFrame) return;
    const player = document.getElementById("output-video-player");
    if (liveSeekTarget !== null && Math.abs(player.currentTime - liveSeekTarget) < 0.15) return;
    const first = firstLiveFrame;
    const last = Math.max(first, latestLiveFrame - Math.ceil(selectedVideo.fps * 0.25));
    const requested = currentSourceFrame(player);
    if (requested < first || requested > last) {
        const boundedFrame = Math.min(last, Math.max(first, requested));
        liveSeekTarget = Math.max(0, (boundedFrame - 1) / selectedVideo.fps);
        player.currentTime = liveSeekTarget;
        livePlaybackWaiting = true;
    }
}

function showSourcePreview(video) {
    const player = document.getElementById("output-video-player");
    const stage = document.querySelector(".video-stage");
    stage.style.aspectRatio = `${video.width} / ${video.height}`;
    stage.style.display = "block";
    player.src = `${API_BASE_URL}/uploads/${encodeURIComponent(video.filename)}`;
    player.onerror = () => {
        const previewUrl = `${API_BASE_URL}/api/videos/${video.id}/preview`;
        if (player.src !== previewUrl) {
            document.getElementById("playback-info").innerText = "Đang chuẩn bị định dạng video để phát trong trình duyệt; AI vẫn tiếp tục phân tích.";
            player.src = previewUrl;
            player.load();
        } else {
            document.getElementById("playback-info").innerText = "Không thể phát video gốc trong trình duyệt. AI vẫn phân tích và sẽ hiển thị video kết quả khi hoàn tất.";
        }
    };
    player.muted = true;
    player.style.display = "block";
    player.onloadedmetadata = () => {
        startLiveOverlay();
        if (firstLiveFrame > 1) player.currentTime = (firstLiveFrame - 1) / video.fps;
        syncLivePlayback();
    };
    player.ontimeupdate = syncLivePlayback;
    player.onseeking = clampLiveSeek;
    player.onseeked = () => {
        if (liveSeekTarget !== null && Math.abs(player.currentTime - liveSeekTarget) < 0.15) liveSeekTarget = null;
        syncLivePlayback();
    };
    startLiveOverlay();
    // Playback starts as soon as the AI has delivered frame one.
    syncLivePlayback();
    document.getElementById("video-placeholder").style.display = "none";
    document.getElementById("playback-info").innerText = `Video gốc ${video.fps.toFixed(1)} FPS · AI đang nhận diện trực tiếp theo từng frame. Video hoàn chỉnh: ${Math.max(60, Math.min(240, Math.ceil(video.fps)))} FPS.`;
}


document.addEventListener("DOMContentLoaded", () => {
    initTabNavigation();
    initBackendHealthCheck();
    initFileUpload();
    restoreSystemSettings();

    canvasEditor = new SetupCanvasEditor("setup-canvas");
    document.getElementById("advanced-setup").addEventListener("toggle", () => canvasEditor.resizeCanvas());
    chartsController = new TrafficChartsController();

    document.getElementById("input-distance-m")?.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value);
        if (Number.isFinite(val) && val > 0) {
            document.getElementById("speed-mode").value = "two_line";
            document.getElementById("chk-enable-speed").checked = true;
        }
    });

    loadAnalysisHistory();
    loadPresetsList();
});

// Tab Navigation
function initTabNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetTab = item.getAttribute("data-tab");
            switchTab(targetTab);
        });
    });
}

function switchTab(tabId) {
    document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));

    const btn = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
    const content = document.getElementById(`tab-${tabId}`);

    if (btn) btn.classList.add("active");
    if (content) content.classList.add("active");

    if (tabId === "analysis" && canvasEditor) requestAnimationFrame(() => canvasEditor.resizeCanvas());
    if (tabId === "history") loadAnalysisHistory();
    if (tabId === "calibration") loadPresetsList();
}

// Backend Health Diagnostic Check
async function initBackendHealthCheck() {
    const badge = document.getElementById("server-status-badge");
    const check = async () => {
        const health = await TrafficVisionAPI.checkHealth();
        if (health && health.status === "online") {
            badge.innerHTML = `
                <span class="status-dot online"></span>
                <span class="status-text" style="color: var(--color-success)">Backend Online</span>
            `;
        } else {
            badge.innerHTML = `
                <span class="status-dot offline"></span>
                <span class="status-text" style="color: var(--color-danger)">Backend Mất kết nối!</span>
            `;
        }
    };
    await check();
    setInterval(check, 5000);
}

// File Upload & Selection
function initFileUpload() {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("video-file-input");

    dropzone.addEventListener("click", () => fileInput.click());

    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.style.borderColor = "var(--color-primary)";
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.style.borderColor = "rgba(255, 255, 255, 0.15)";
    });

    dropzone.addEventListener("drop", async (e) => {
        e.preventDefault();
        dropzone.style.borderColor = "rgba(255, 255, 255, 0.15)";
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            await handleFileSelected(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener("change", async () => {
        if (fileInput.files && fileInput.files.length > 0) {
            await handleFileSelected(fileInput.files[0]);
        }
    });
}

function setUploadBusy(busy) {
    document.getElementById("video-file-input").disabled = busy;
    document.getElementById("btn-use-sample").disabled = busy;
    document.getElementById("dropzone").style.opacity = busy ? "0.5" : "1";
}

async function prepareAutomaticSetup(videoObj) {
    setVideoSelection(videoObj);
    document.getElementById("auto-setup-status").innerText = "Đang xác định vùng quan sát và tự vẽ các vạch...";
    const config = await TrafficVisionAPI.autoSetup(videoObj.id);
    canvasEditor.loadConfig(config);
    document.getElementById("chk-enable-count").checked = true;
    document.getElementById("chk-enable-speed").checked = true;
    document.getElementById("speed-mode").value = "auto";
    document.getElementById("input-distance-m").value = "";
    document.getElementById("auto-setup-status").innerText = "Đã tự đặt vùng quan sát, vạch đếm và bật đo tốc độ tự động (km/h).";
    document.getElementById("avg-speed-sub").innerText = "Đang tự động ước lượng tốc độ (km/h) theo kích thước phương tiện & phối cảnh.";
}

async function handleFileSelected(file) {
    if (preparingVideo || analysisRunning) return;
    preparingVideo = true;
    setUploadBusy(true);
    switchTab("analysis");
    try {
        const metaBox = document.getElementById("video-meta-box");
        metaBox.style.opacity = "0.5";
        document.getElementById("meta-filename").innerText = "Đang upload & kiểm tra...";

        const videoObj = await TrafficVisionAPI.uploadVideo(file);
        await prepareAutomaticSetup(videoObj);
        await startAnalysisSession(true);
    } catch (err) {
        document.getElementById("auto-setup-status").innerText = "Không thể chuẩn bị video: " + err.message;
        alert("Không thể chuẩn bị video: " + err.message);
    } finally {
        document.getElementById("video-meta-box").style.opacity = "1";
        preparingVideo = false;
        setUploadBusy(analysisRunning);
        document.getElementById("video-file-input").value = "";
    }
}

async function loadSampleVideoAndStart(autoStart = true) {
    if (preparingVideo || analysisRunning) return;
    preparingVideo = true;
    setUploadBusy(true);
    switchTab("analysis");
    try {
        const sample = await TrafficVisionAPI.createSampleVideo();
        await prepareAutomaticSetup(sample);
        document.getElementById("detection-mode").value = "demo";
        document.getElementById("demo-notice").style.display = "block";
        if (autoStart) await startAnalysisSession(true);
    } catch (err) {
        document.getElementById("auto-setup-status").innerText = "Không thể chuẩn bị video mẫu: " + err.message;
        alert("Không thể tải video mẫu: " + err.message);
    } finally {
        preparingVideo = false;
        setUploadBusy(analysisRunning);
    }
}

function setVideoSelection(videoObj) {
    selectedVideo = videoObj;
    canvasEditor.clearAll();
    document.getElementById("detection-mode").value = "yolo";
    document.getElementById("meta-filename").innerText = videoObj.original_name;
    document.getElementById("demo-notice").style.display = "none";
    document.getElementById("meta-resolution").innerText = `${videoObj.width} x ${videoObj.height}`;
    document.getElementById("meta-fps").innerText = `${videoObj.fps}`;
    document.getElementById("meta-duration").innerText = `${videoObj.duration_sec}s`;
    document.getElementById("meta-frames").innerText = `${videoObj.total_frames}`;

    // Load first frame for interactive canvas setup
    const frameUrl = TrafficVisionAPI.getVideoFrameUrl(videoObj.id, 1);
    canvasEditor.setFrameImage(frameUrl);
    document.getElementById("canvas-msg").style.display = "none";

    // New videos always receive their own setup; old camera distances are not reused.
}

// Canvas Tools & Drawing
function setDrawingTool(toolName) {
    document.querySelectorAll(".tool-btn").forEach(btn => btn.classList.remove("active"));
    const btn = document.getElementById(`tool-${toolName.replace("_", "-")}`);
    if (btn) btn.classList.add("active");
    canvasEditor.setTool(toolName);
}

function clearCanvasDrawing() {
    canvasEditor.clearAll();
}

// Session Controls: Start, Cancel, Rerun
async function startAnalysisSession(autoPrepared = false) {
    if (analysisRunning || (preparingVideo && !autoPrepared)) return;
    if (!selectedVideo) {
        alert("Vui lòng chọn hoặc upload video trước khi khởi chạy phân tích.");
        return;
    }

    const canvasConfig = canvasEditor.getConfig();
    const enableSpeed = document.getElementById("chk-enable-speed").checked;
    const speedMode = document.getElementById("speed-mode").value || "auto";
    const distanceMeters = parseFloat(document.getElementById("input-distance-m").value);
    const enableCount = document.getElementById("chk-enable-count").checked;

    const pendingTool = canvasEditor.dragState?.tool;
    if ((enableSpeed && speedMode === "two_line" && ["line_a", "line_b"].includes(pendingTool)) || (enableCount && pendingTool === "count")) {
        return alert("Vạch đang vẽ chưa hoàn tất. Bấm điểm thứ hai hoặc kéo để tạo vạch; chọn công cụ khác để bỏ nét đang vẽ.");
    }
    if (enableCount && !canvasConfig.count_line) return alert("Vui lòng vẽ vạch đếm xe hoặc tắt đếm qua vạch.");
    if (enableSpeed && speedMode === "two_line" && (!canvasConfig.line_a || !canvasConfig.line_b)) return alert("Vui lòng vẽ đủ vạch A và B hoặc chuyển sang chế độ đo tự động.");
    if (enableSpeed && speedMode === "two_line" && (!Number.isFinite(distanceMeters) || distanceMeters <= 0)) return alert("Khoảng cách thực phải lớn hơn 0 mét.");
    const targetClasses = [...document.querySelectorAll(".setting-cls:checked")].map(el => Number(el.value));
    if (!targetClasses.length) return alert("Chọn ít nhất một loại phương tiện.");

    // Build session payload
    const payload = {
        video_id: selectedVideo.id,
        confidence_threshold: parseFloat(document.getElementById("setting-conf").value) || 0.35,
        target_classes: targetClasses,
        detection_mode: document.getElementById("detection-mode").value,
        roi_polygon: canvasConfig.roi_polygon,
        counting_line: {
            enabled: enableCount && !!canvasConfig.count_line,
            line: enableCount ? canvasConfig.count_line : null,
            direction: "both"
        },
        speed_calibration: {
            enabled: enableSpeed && (speedMode === "auto" || (!!canvasConfig.line_a && !!canvasConfig.line_b)),
            mode: speedMode,
            line_a: (enableSpeed && speedMode === "two_line") ? canvasConfig.line_a : null,
            line_b: (enableSpeed && speedMode === "two_line") ? canvasConfig.line_b : null,
            distance_meters: (enableSpeed && speedMode === "two_line") ? distanceMeters : 10
        },
        congestion_thresholds: {
            max_occupancy_heavy: parseInt(document.getElementById("setting-occupancy").value) || 8,
            slow_speed_threshold_kmh: parseFloat(document.getElementById("setting-slow-speed").value) || 20.0,
            slow_vehicle_ratio_threshold: (parseFloat(document.getElementById("setting-slow-ratio").value) || 50) / 100.0,
            min_duration_seconds: Number(document.getElementById("setting-duration").value),
            min_valid_speed_samples: 1
        },
        save_annotated_video: true,
        output_fps: Math.max(60, Math.min(240, Math.ceil(selectedVideo.fps))),
        live_overlay_fps: 60,
        frame_skip: Math.max(1, Math.min(10, Math.ceil(selectedVideo.fps / 60))),
        motorcycle_confidence_threshold: 0.20
    };

    try {
        analysisRunning = true;
        setUploadBusy(true);
        document.getElementById("avg-speed-sub").innerText = !enableSpeed
            ? "Đã tắt đo tốc độ; đang phân tích số xe và mật độ."
            : (speedMode === "auto"
                ? "Đang tự động ước lượng tốc độ (km/h) theo kích thước phương tiện & phối cảnh."
                : "Dựa trên các phép đo hợp lệ qua hai vạch đã hiệu chỉnh.");
        document.getElementById("btn-start-session").disabled = true;
        document.getElementById("btn-cancel-session").disabled = false;
        document.getElementById("btn-rerun-session").disabled = true;

        document.getElementById("results-dashboard").style.display = "block";
        document.getElementById("results-dashboard").scrollIntoView({ behavior: "smooth" });

        resetResults();
        showSourcePreview(selectedVideo);

        const sessionObj = await TrafficVisionAPI.startSession(payload);
        activeSessionId = sessionObj.id;

        initSessionWebSocket(sessionObj.id);
        pollSessionState(sessionObj.id);

    } catch (err) {
        analysisRunning = false;
        setUploadBusy(preparingVideo);
        alert("Lỗi khởi tạo phiên phân tích: " + err.message);
        document.getElementById("btn-start-session").disabled = false;
        document.getElementById("btn-cancel-session").disabled = true;
    }
}

async function cancelAnalysisSession() {
    if (!activeSessionId || !confirm("Hủy phiên phân tích đang chạy?")) return;
    try {
        await TrafficVisionAPI.cancelSession(activeSessionId);
        document.getElementById("btn-cancel-session").disabled = true;
    } catch (error) { alert(error.message); }
}

async function rerunAnalysisSession() {
    if (!activeSessionId || preparingVideo || analysisRunning) return;
    analysisRunning = true;
    setUploadBusy(true);
    document.getElementById("btn-rerun-session").disabled = true;
    document.getElementById("btn-start-session").disabled = true;
    try {
        const newSession = await TrafficVisionAPI.rerunSession(activeSessionId);
        activeSessionId = newSession.id;
        resetResults();
        if (!selectedVideo || selectedVideo.id !== newSession.video_id) {
            selectedVideo = await TrafficVisionAPI.getVideo(newSession.video_id);
        }
        showSourcePreview(selectedVideo);
        document.getElementById("btn-cancel-session").disabled = false;
        initSessionWebSocket(newSession.id);
        pollSessionState(newSession.id);
    } catch (err) {
        analysisRunning = false;
        setUploadBusy(false);
        alert("Lỗi khi chạy lại phiên: " + err.message);
        document.getElementById("btn-start-session").disabled = false;
        document.getElementById("btn-rerun-session").disabled = false;
    }
}

// WebSocket & Polling Handler
function initSessionWebSocket(sessionId) {
    if (activeWebSocket) {
        activeWebSocket.close();
    }

    activeWebSocket = TrafficVisionAPI.connectWebSocket(sessionId, (data) => {
        if (sessionId !== activeSessionId) return;
        if (data.kind === "tracks") {
            liveOverlayFrames.set(data.frame_idx, data.tracks || []);
            if (!firstLiveFrame) {
                firstLiveFrame = data.frame_idx;
                const player = document.getElementById("output-video-player");
                if (player.videoWidth && firstLiveFrame > 1) player.currentTime = data.timestamp_sec;
                livePlaybackWaiting = true;
            }
            latestLiveFrame = Math.max(latestLiveFrame, data.frame_idx || 0);
            if (liveOverlayFrames.size > 20000) {
                while (liveOverlayFrames.size > 18000) {
                    liveOverlayFrames.delete(liveOverlayFrames.keys().next().value);
                }
                firstLiveFrame = liveOverlayFrames.keys().next().value;
                clampLiveSeek();
            }
            syncLivePlayback();
            return;
        }
        updateLiveProgress(data);
    });
}

function updateLiveProgress(data) {
    const pct = data.progress_pct || 0;
    document.getElementById("progress-bar-fill").style.width = `${pct}%`;
    document.getElementById("progress-pct-text").innerText = `${pct.toFixed(1)}%`;

    document.getElementById("session-status-title").innerText = `Trạng thái: Đang phân tích frame (${data.processed_frames} / ${data.total_frames})`;
    document.getElementById("session-speed-eta").innerText = `Tốc độ xử lý: ${data.processing_fps} FPS | Thời gian còn lại (ETA): ${data.eta_sec}s`;

    updateTrafficStatusBadge(data.traffic_status, data.reason);

    if (data.avg_speed_kmh !== null && data.avg_speed_kmh !== undefined) {
        document.getElementById("avg-speed-text").innerHTML = `${data.avg_speed_kmh} <small>km/h</small>`;
    } else {
        document.getElementById("avg-speed-text").innerHTML = `-- <small>km/h</small>`;
    }
}

async function pollSessionState(sessionId) {
    const generation = ++pollGeneration;
    let lastCongestionFrame = 0;
    const congestionTimeline = [];
    const poll = async () => {
        if (generation !== pollGeneration) return;
        let terminal = false;
        try {
            const details = await TrafficVisionAPI.getSessionDetails(sessionId, lastCongestionFrame);
            if (generation !== pollGeneration) return;
            updateLiveProgress({progress_pct: details.progress_pct, processed_frames: details.processed_frames,
                total_frames: details.total_frames, processing_fps: details.processing_fps,
                eta_sec: details.estimated_time_remaining_sec, traffic_status: details.final_traffic_status,
                reason: details.final_status_reason, avg_speed_kmh: details.avg_speed_kmh});

            const running = ["pending", "processing"].includes(details.status);
            analysisRunning = running;
            setUploadBusy(running || preparingVideo);
            document.getElementById("btn-start-session").disabled = running;
            document.getElementById("btn-cancel-session").disabled = !running;
            document.getElementById("btn-rerun-session").disabled = running;
            // Update Counts
            document.getElementById("count-car").innerText = details.car_count;
            document.getElementById("count-moto").innerText = details.motorcycle_count;
            document.getElementById("count-bus").innerText = details.bus_count;
            document.getElementById("count-truck").innerText = details.truck_count;

            updateTrafficStatusBadge(details.final_traffic_status, details.final_status_reason);

            if (details.avg_speed_kmh !== null) {
                document.getElementById("avg-speed-text").innerHTML = `${details.avg_speed_kmh} <small>km/h</small>`;
            }

            // Update Charts
            if (details.congestion_timeline && details.congestion_timeline.length > 0) {
                congestionTimeline.push(...details.congestion_timeline);
                lastCongestionFrame = details.congestion_timeline.at(-1).frame_idx;
                chartsController.updateData(congestionTimeline);
            }

            // Update Vehicle Table
            updateVehicleTable(details.recent_records);

            if (details.status === "completed" || details.status === "failed" || details.status === "cancelled") {
                terminal = true;
                analysisRunning = false;
                setUploadBusy(preparingVideo);
                if (activeWebSocket) { activeWebSocket.close(); activeWebSocket = null; }
                document.getElementById("btn-start-session").disabled = false;
                document.getElementById("btn-cancel-session").disabled = true;
                document.getElementById("btn-rerun-session").disabled = false;

                if (details.status === "completed") {
                    document.getElementById("progress-bar-fill").style.width = "100%";
                    document.getElementById("progress-pct-text").innerText = "100%";
                    document.getElementById("session-status-title").innerText = "Trạng thái: Phân tích hoàn tất thành công!";
                    document.getElementById("session-speed-eta").innerText = `Hoàn tất lúc ${utcDate(details.completed_at).toLocaleTimeString()}`;

                    // Show video output player and export links
                    if (details.annotated_video_path) {
                        const player = document.getElementById("output-video-player");
                        const resumeAt = player.currentTime || 0;
                        resetLiveOverlay();
                        const stage = document.querySelector(".video-stage");
                        const resultVideo = selectedVideo?.id === details.video_id
                            ? selectedVideo : await TrafficVisionAPI.getVideo(details.video_id);
                        stage.style.aspectRatio = `${resultVideo.width} / ${resultVideo.height}`;
                        stage.style.display = "block";
                        player.src = `${API_BASE_URL}/api/reports/sessions/${sessionId}/video`;
                        player.onloadedmetadata = () => {
                            if (generation !== pollGeneration) return;
                            if (resumeAt > 0) player.currentTime = Math.min(resumeAt, Math.max(0, player.duration - 0.05));
                            player.play().catch(() => {});
                        };
                        document.getElementById("playback-info").innerText = `Video kết quả AI · ${details.config.output_fps || "FPS gốc"} FPS`;
                        player.style.display = "block";
                        document.getElementById("video-placeholder").style.display = "none";
                    }

                    document.getElementById("btn-download-csv").style.display = details.csv_report_path ? "" : "none";
                    document.getElementById("btn-download-video").style.display = details.annotated_video_path ? "" : "none";
                    document.getElementById("btn-download-csv").href = `${API_BASE_URL}/api/reports/sessions/${sessionId}/csv`;
                    document.getElementById("btn-download-video").href = `${API_BASE_URL}/api/reports/sessions/${sessionId}/video`;
                } else if (details.status === "cancelled") {
                    document.getElementById("session-status-title").innerText = "Trạng thái: Đã hủy phiên phân tích.";
                } else if (details.status === "failed") {
                    document.getElementById("session-status-title").innerText = `Trạng thái thất bại: ${details.error_message || "Lỗi xử lý video"}`;
                }
            }
        } catch (err) {
            console.error("Polling error:", err);
        }
        if (!terminal && generation === pollGeneration) setTimeout(poll, 1500);
    };
    poll();
}

function updateTrafficStatusBadge(status, reason) {
    const badge = document.getElementById("traffic-status-text");
    const reasonEl = document.getElementById("traffic-status-reason");

    badge.innerText = status || "Chưa đủ dữ liệu";
    reasonEl.innerText = reason || "";

    badge.className = "traffic-status-badge ";
    if (status === "Thông thoáng") badge.classList.add("text-clear");
    else if (status === "Đông xe") badge.classList.add("text-moderate");
    else if (status === "Ùn tắc") badge.classList.add("text-congested");
    else badge.classList.add("text-insufficient");
}

function updateVehicleTable(records) {
    const tbody = document.getElementById("vehicle-table-body");
    if (!records || records.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Chưa có dữ liệu phương tiện</td></tr>`;
        return;
    }

    tbody.innerHTML = records.map(r => `
        <tr>
            <td>#${r.track_id}</td>
            <td><strong>${r.vehicle_type}</strong></td>
            <td>${r.first_seen_sec.toFixed(1)}s - ${r.last_seen_sec.toFixed(1)}s</td>
            <td>${r.direction || "N/A"}</td>
            <td>${r.speed_kmh !== null ? `<strong style="color:var(--color-primary)">${r.speed_kmh} km/h</strong>` : `<span class="text-muted">Chưa đủ dữ liệu</span>`}</td>
            <td>
                <span class="brand-badge" style="background: ${r.is_valid_speed ? 'rgba(16,185,129,0.2)' : 'rgba(255,255,255,0.1)'}; color: ${r.is_valid_speed ? 'var(--color-success)' : 'var(--text-muted)'}">
                    ${r.speed_status_reason}
                </span>
            </td>
        </tr>
    `).join("");
}

// History List Loader
async function loadAnalysisHistory() {
    try {
        const sessions = await TrafficVisionAPI.listHistorySessions();
        const tbody = document.getElementById("history-table-body");
        
        // Update KPI metrics on overview page
        document.getElementById("kpi-total-sessions").innerText = sessions.length;
        const totalVeh = sessions.reduce((acc, s) => acc + (s.total_vehicles_counted || 0), 0);
        document.getElementById("kpi-total-vehicles").innerText = totalVeh;

        const validSpeeds = sessions.map(s => s.avg_speed_kmh).filter(v => v !== null);
        const avgGlobal = validSpeeds.length > 0 ? (validSpeeds.reduce((a, b) => a + b, 0) / validSpeeds.length).toFixed(1) : "--";
        document.getElementById("kpi-avg-speed").innerText = `${avgGlobal} km/h`;

        if (!sessions || sessions.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">Chưa có phiên phân tích nào được lưu.</td></tr>`;
            return;
        }

        tbody.innerHTML = sessions.map(s => `
            <tr>
                <td>#${s.id}</td>
                <td>${utcDate(s.created_at).toLocaleString("vi-VN")}</td>
                <td><span class="brand-badge">${s.status}</span></td>
                <td>${s.total_vehicles_counted} xe</td>
                <td>${s.avg_speed_kmh !== null ? `${s.avg_speed_kmh} km/h` : 'Chưa đủ dữ liệu'}</td>
                <td><strong>${s.final_traffic_status}</strong></td>
                <td>
                    <div class="flex-align gap-10">
                        <button class="btn btn-sm btn-secondary" onclick="viewHistoryDetail(${s.id})">Xem lại</button>
                        ${s.csv_report_path ? `<a class="btn btn-sm btn-outline-primary" href="${API_BASE_URL}/api/reports/sessions/${s.id}/csv" download>CSV</a>` : ''}
                    </div>
                </td>
            </tr>
        `).join("");
    } catch (err) {
        console.error("Lỗi tải lịch sử:", err);
    }
}

async function viewHistoryDetail(sessionId) {
    switchTab("analysis");
    activeSessionId = sessionId;
    resetResults();
    document.getElementById("results-dashboard").style.display = "block";
    document.getElementById("results-dashboard").scrollIntoView({ behavior: "smooth" });
    try {
        const details = await TrafficVisionAPI.getSessionDetails(sessionId, 0);
        if (sessionId !== activeSessionId) return;
        if (["pending", "processing"].includes(details.status)) {
            selectedVideo = await TrafficVisionAPI.getVideo(details.video_id);
            if (sessionId !== activeSessionId) return;
            showSourcePreview(selectedVideo);
            initSessionWebSocket(sessionId);
        }
    } catch (error) {
        console.error("Không thể mở phiên phân tích:", error);
    }
    pollSessionState(sessionId);
}

// Preset Manager Functions
async function loadPresetsList() {
    try {
        const presets = await TrafficVisionAPI.listPresets();
        const container = document.getElementById("preset-list");
        if (!presets || presets.length === 0) {
            container.innerHTML = `<p class="text-muted">Chưa có cấu hình nào được lưu.</p>`;
            return;
        }

        container.innerHTML = presets.map(p => `
            <div class="card glass mb-15 flex-between">
                <div>
                    <strong>${escapeHtml(p.name)}</strong>
                    <p class="text-muted" style="font-size:12px;">${escapeHtml(p.description || 'Không có mô tả')}</p>
                </div>
                <div class="flex-align gap-10">
                    <button class="btn btn-sm btn-primary" onclick="applyPreset(${p.id})">Áp dụng</button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deletePreset(${p.id})">Xóa</button>
                </div>
            </div>
        `).join("");
    } catch (err) {
        console.error("Lỗi tải preset:", err);
    }
}

function openSavePresetModal() {
    document.getElementById("modal-save-preset").style.display = "flex";
}

function closeSavePresetModal() {
    document.getElementById("modal-save-preset").style.display = "none";
}

async function confirmSavePreset() {
    const name = document.getElementById("preset-name-input").value.trim();
    const desc = document.getElementById("preset-desc-input").value.trim();
    if (!name) {
        alert("Vui lòng nhập tên cấu hình.");
        return;
    }

    const config = {...canvasEditor.getConfig(), distance_meters: Number(document.getElementById("input-distance-m").value),
        speed_enabled: document.getElementById("chk-enable-speed").checked, speed_mode: document.getElementById("speed-mode").value,
        count_enabled: document.getElementById("chk-enable-count").checked};
    try {
        await TrafficVisionAPI.savePreset(name, desc, config);
        closeSavePresetModal();
        loadPresetsList();
        alert("Lưu cấu hình camera thành công!");
    } catch (err) {
        alert("Lỗi lưu preset: " + err.message);
    }
}

async function applyPreset(presetId) {
    const presets = await TrafficVisionAPI.listPresets();
    const p = presets.find(item => item.id === presetId);
    if (p) {
        const config = JSON.parse(p.config_json);
        currentPresetConfig = config;
        canvasEditor.loadConfig(config);
        document.getElementById("speed-mode").value = config.speed_mode || (config.distance_meters ? "two_line" : "auto");
        document.getElementById("input-distance-m").value = config.distance_meters || "";
        document.getElementById("chk-enable-speed").checked = config.speed_enabled ?? true;
        document.getElementById("chk-enable-count").checked = config.count_enabled ?? !!config.count_line;
        switchTab("analysis");
        alert(`Đã áp dụng cấu hình: ${p.name}`);
    }
}

async function deletePreset(presetId) {
    if (confirm("Bạn có chắc muốn xóa cấu hình này?")) {
        await TrafficVisionAPI.deletePreset(presetId);
        loadPresetsList();
    }
}

function saveSystemSettings() {
    const saved = {};
    for (const id of settingIds) {
        const element = document.getElementById(id);
        if (!element.checkValidity() || !Number.isFinite(Number(element.value)) || element.value === "") return alert("Kiểm tra lại ngưỡng cài đặt.");
        saved[id] = element.value;
    }
    saved.classes = [...document.querySelectorAll(".setting-cls:checked")].map(el => Number(el.value));
    saved.vehicle_defaults_v2 = true;
    if (!saved.classes.length) return alert("Chọn ít nhất một loại phương tiện.");
    try { localStorage.setItem("its-settings", JSON.stringify(saved)); }
    catch (error) { return alert("Không thể lưu cài đặt vào trình duyệt."); }
    alert("Đã lưu các cài đặt hệ thống thành công!");
}
