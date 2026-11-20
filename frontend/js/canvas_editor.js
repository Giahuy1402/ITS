class SetupCanvasEditor {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext("2d");
        this.currentTool = "roi"; // roi, line_a, line_b, count

        this.backgroundImage = new Image();
        this.bgLoaded = false;

        // Coordinates normalized (0.0 to 1.0)
        this.roiPolygon = []; // [{x, y}, ...]
        this.lineA = null;    // {p1: {x, y}, p2: {x, y}}
        this.lineB = null;    // {p1: {x, y}, p2: {x, y}}
        this.countLine = null;// {p1: {x, y}, p2: {x, y}}

        this.dragState = null; // {tool, p1, p2}

        this.initEvents();
    }

    setFrameImage(imageUrl) {
        this.bgLoaded = false;
        this.backgroundImage.onload = () => {
            this.bgLoaded = true;
            this.resizeCanvas();
            this.render();
        };
        this.backgroundImage.onerror = () => { document.getElementById("canvas-msg").style.display = "block"; };
        this.backgroundImage.src = imageUrl;
    }

    resizeCanvas() {
        if (!this.bgLoaded) return;
        const container = this.canvas.parentElement;
        const containerWidth = container.clientWidth;
        
        // Maintain video aspect ratio
        const aspect = this.backgroundImage.naturalHeight / this.backgroundImage.naturalWidth;
        this.canvas.width = containerWidth;
        this.canvas.height = containerWidth * aspect;
        this.render();
    }

    initEvents() {
        window.addEventListener("resize", () => this.resizeCanvas());

        this.canvas.addEventListener("pointerdown", (e) => { this.canvas.setPointerCapture(e.pointerId); this.handleMouseDown(e); });
        this.canvas.addEventListener("pointermove", (e) => this.handleMouseMove(e));
        this.canvas.addEventListener("pointerup", (e) => this.handleMouseUp(e));
        this.canvas.addEventListener("pointercancel", () => { this.dragState = null; this.render(); });
    }

    getCanvasPos(e) {
        const rect = this.canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width;
        const y = (e.clientY - rect.top) / rect.height;
        return { x: Math.min(Math.max(x, 0), 1), y: Math.min(Math.max(y, 0), 1) };
    }

    handleMouseDown(e) {
        if (!this.bgLoaded || (e.button !== undefined && e.button !== 0)) return;
        const pos = this.getCanvasPos(e);

        if (this.currentTool === "roi") {
            this.roiPolygon.push(pos);
            this.render();
        } else {
            // A short press sets the first endpoint; a second press finishes it.
            const start = this.dragState?.waiting && this.dragState.tool === this.currentTool
                ? this.dragState.p1 : pos;
            this.dragState = {tool: this.currentTool, p1: start, p2: pos, waiting: false};
            this.render();
        }
    }

    handleMouseMove(e) {
        if (!this.dragState) return;
        this.dragState.p2 = this.getCanvasPos(e);
        this.render();
    }

    handleMouseUp(e) {
        if (!this.dragState) return;
        this.dragState.p2 = this.getCanvasPos(e);
        const rect = this.canvas.getBoundingClientRect();
        const length = Math.hypot((this.dragState.p2.x - this.dragState.p1.x) * rect.width,
                                  (this.dragState.p2.y - this.dragState.p1.y) * rect.height);
        if (length < 4) {
            this.dragState.waiting = true;
            this.render();
            return;
        }

        if (this.dragState.tool === "line_a") {
            this.lineA = { p1: this.dragState.p1, p2: this.dragState.p2 };
        } else if (this.dragState.tool === "line_b") {
            this.lineB = { p1: this.dragState.p1, p2: this.dragState.p2 };
        } else if (this.dragState.tool === "count") {
            this.countLine = { p1: this.dragState.p1, p2: this.dragState.p2 };
        }

        this.dragState = null;
        this.render();
    }

    setTool(toolName) {
        if (this.currentTool !== toolName) this.dragState = null;
        this.currentTool = toolName;
        this.render();
    }

    clearAll() {
        this.dragState = null;
        this.roiPolygon = [];
        this.lineA = null;
        this.lineB = null;
        this.countLine = null;
        this.render();
    }

    render() {
        const w = this.canvas.width;
        const h = this.canvas.height;
        this.ctx.clearRect(0, 0, w, h);

        if (this.bgLoaded) {
            this.ctx.drawImage(this.backgroundImage, 0, 0, w, h);
        }

        // 1. Draw ROI Polygon
        if (this.roiPolygon.length > 0) {
            this.ctx.beginPath();
            this.ctx.moveTo(this.roiPolygon[0].x * w, this.roiPolygon[0].y * h);
            for (let i = 1; i < this.roiPolygon.length; i++) {
                this.ctx.lineTo(this.roiPolygon[i].x * w, this.roiPolygon[i].y * h);
            }
            if (this.roiPolygon.length >= 3) {
                this.ctx.closePath();
                this.ctx.fillStyle = "rgba(255, 255, 0, 0.15)";
                this.ctx.fill();
            }
            this.ctx.strokeStyle = "#FFFF00";
            this.ctx.lineWidth = 2;
            this.ctx.stroke();

            // Draw ROI points
            this.roiPolygon.forEach(p => {
                this.ctx.beginPath();
                this.ctx.arc(p.x * w, p.y * h, 4, 0, 2 * Math.PI);
                this.ctx.fillStyle = "#FFFF00";
                this.ctx.fill();
            });
        }

        // 2. Draw Line A
        if (this.lineA) {
            this.drawLine(this.lineA.p1, this.lineA.p2, "#FF00FF", "Vạch A (Mốc 1)");
        }

        // 3. Draw Line B
        if (this.lineB) {
            this.drawLine(this.lineB.p1, this.lineB.p2, "#FFA500", "Vạch B (Mốc 2)");
        }

        // 4. Draw Count Line
        if (this.countLine) {
            this.drawLine(this.countLine.p1, this.countLine.p2, "#00FFFF", "Vạch Đếm Xe");
        }

        // 5. Draw active drag line
        if (this.dragState) {
            const colorMap = { line_a: "#FF00FF", line_b: "#FFA500", count: "#00FFFF" };
            this.drawLine(this.dragState.p1, this.dragState.p2, colorMap[this.dragState.tool] || "#FFF",
                this.dragState.waiting ? "Chọn điểm thứ hai" : "Đang vẽ...");
            this.ctx.beginPath();
            this.ctx.arc(this.dragState.p1.x * w, this.dragState.p1.y * h, 5, 0, 2 * Math.PI);
            this.ctx.fill();
        }
    }

    drawLine(p1, p2, color, label) {
        const w = this.canvas.width;
        const h = this.canvas.height;
        this.ctx.beginPath();
        this.ctx.moveTo(p1.x * w, p1.y * h);
        this.ctx.lineTo(p2.x * w, p2.y * h);
        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = 3;
        this.ctx.stroke();

        this.ctx.font = "12px sans-serif";
        this.ctx.fillStyle = color;
        this.ctx.fillText(label, p1.x * w + 5, p1.y * h - 5);
    }

    static isValidLine(line) {
        if (!line?.p1 || !line?.p2) return false;
        const coordinates = [line.p1.x, line.p1.y, line.p2.x, line.p2.y];
        return coordinates.every(value => Number.isFinite(value) && value >= 0 && value <= 1)
            && Math.hypot(line.p2.x - line.p1.x, line.p2.y - line.p1.y) > 1e-6;
    }

    getConfig() {
        return {
            roi_polygon: this.roiPolygon,
            line_a: SetupCanvasEditor.isValidLine(this.lineA) ? this.lineA : null,
            line_b: SetupCanvasEditor.isValidLine(this.lineB) ? this.lineB : null,
            count_line: SetupCanvasEditor.isValidLine(this.countLine) ? this.countLine : null
        };
    }

    loadConfig(config) {
        this.dragState = null;
        this.roiPolygon = config.roi_polygon || [];
        this.lineA = SetupCanvasEditor.isValidLine(config.line_a) ? config.line_a : null;
        this.lineB = SetupCanvasEditor.isValidLine(config.line_b) ? config.line_b : null;
        this.countLine = SetupCanvasEditor.isValidLine(config.count_line) ? config.count_line : null;
        this.render();
    }
}
