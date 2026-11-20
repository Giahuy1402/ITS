const API_BASE_URL = window.location.origin;

function apiError(data, fallback) {
    if (Array.isArray(data.detail)) return data.detail.map(e => `${e.loc.slice(1).join(".")}: ${e.msg}`).join("; ");
    return typeof data.detail === "string" ? data.detail : fallback;
}

class TrafficVisionAPI {
    static async createSampleVideo() {
        const res = await fetch(`${API_BASE_URL}/api/videos/sample`, {method: "POST"});
        if (!res.ok) throw new Error(apiError(await res.json(), "Không thể tạo video mẫu."));
        return res.json();
    }

    static async checkHealth() {
        try {
            const res = await fetch(`${API_BASE_URL}/api/health`);
            if (res.ok) {
                return await res.json();
            }
            return null;
        } catch (err) {
            return null;
        }
    }

    static async uploadVideo(file) {
        const formData = new FormData();
        formData.append("file", file);

        const res = await fetch(`${API_BASE_URL}/api/videos/upload`, {
            method: "POST",
            body: formData
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(apiError(errData, "Upload video thất bại."));
        }
        return await res.json();
    }

    static async autoSetup(videoId) {
        const res = await fetch(`${API_BASE_URL}/api/videos/${videoId}/auto-setup`);
        if (!res.ok) throw new Error(apiError(await res.json(), "Không thể thiết lập vạch tự động."));
        return res.json();
    }

    static async listVideos() {
        const res = await fetch(`${API_BASE_URL}/api/videos`);
        if (!res.ok) throw new Error("Không thể lấy danh sách video.");
        return await res.json();
    }

    static async getVideo(videoId) {
        const res = await fetch(`${API_BASE_URL}/api/videos/${videoId}`);
        if (!res.ok) throw new Error("Không thể tải thông tin video.");
        return await res.json();
    }

    static getVideoFrameUrl(videoId, frameIdx = 1) {
        return `${API_BASE_URL}/api/videos/${videoId}/frame?frame_idx=${frameIdx}&t=${Date.now()}`;
    }

    static async startSession(configData) {
        const res = await fetch(`${API_BASE_URL}/api/sessions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(configData)
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(apiError(errData, "Khởi tạo phiên thất bại."));
        }
        return await res.json();
    }

    static async getSessionDetails(sessionId, sinceFrame = null) {
        const query = sinceFrame === null ? "" : `?since_frame=${sinceFrame}`;
        const res = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}${query}`);
        if (!res.ok) throw new Error("Không thể lấy chi tiết phiên phân tích.");
        return await res.json();
    }

    static async cancelSession(sessionId) {
        const res = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}/cancel`, {
            method: "POST"
        });
        if (!res.ok) throw new Error(apiError(await res.json(), "Không thể hủy phiên."));
        return await res.json();
    }

    static async rerunSession(sessionId) {
        const res = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}/rerun`, {
            method: "POST"
        });
        if (!res.ok) throw new Error("Chạy lại phiên thất bại.");
        return await res.json();
    }

    static async listHistorySessions() {
        const res = await fetch(`${API_BASE_URL}/api/reports/sessions`);
        if (!res.ok) throw new Error("Không thể tải lịch sử phân tích.");
        return await res.json();
    }

    static async listPresets() {
        const res = await fetch(`${API_BASE_URL}/api/calibration`);
        if (!res.ok) throw new Error("Không thể tải cấu hình hiệu chỉnh.");
        return await res.json();
    }

    static async savePreset(name, description, config) {
        const res = await fetch(`${API_BASE_URL}/api/calibration`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, description, config })
        });
        if (!res.ok) throw new Error("Không thể lưu cấu hình hiệu chỉnh.");
        return await res.json();
    }

    static async deletePreset(presetId) {
        const res = await fetch(`${API_BASE_URL}/api/calibration/${presetId}`, {
            method: "DELETE"
        });
        return await res.json();
    }

    static connectWebSocket(sessionId, onMessageCallback) {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/api/sessions/ws/${sessionId}`;

        const ws = new WebSocket(wsUrl);
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                onMessageCallback(data);
            } catch (err) {
                console.error("WS parse error:", err);
            }
        };

        ws.onerror = (error) => {
            console.warn("WebSocket error:", error);
        };

        return ws;
    }
}
