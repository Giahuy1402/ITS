class TrafficChartsController {
    constructor() {
        this.chartFlowSpeed = null;
        this.chartCongestion = null;
        this.initCharts();
    }

    initCharts() {
        if (typeof Chart === "undefined") return;
        // 1. Flow & Speed Line Chart
        const ctx1 = document.getElementById("chart-flow-speed").getContext("2d");
        this.chartFlowSpeed = new Chart(ctx1, {
            type: "line",
            data: {
                labels: [],
                datasets: [
                    {
                        label: "Số xe trong ROI",
                        data: [],
                        borderColor: "#3B82F6",
                        backgroundColor: "rgba(59, 130, 246, 0.1)",
                        yAxisID: "y_count",
                        tension: 0.3,
                        fill: true
                    },
                    {
                        label: "Tốc độ trung bình (km/h)",
                        data: [],
                        borderColor: "#10B981",
                        backgroundColor: "transparent",
                        yAxisID: "y_speed",
                        tension: 0.3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        ticks: { color: "#9CA3AF" },
                        grid: { color: "rgba(255, 255, 255, 0.05)" }
                    },
                    y_count: {
                        type: "linear",
                        position: "left",
                        title: { display: true, text: "Số xe (chiếc)", color: "#3B82F6" },
                        ticks: { color: "#9CA3AF" },
                        grid: { color: "rgba(255, 255, 255, 0.05)" }
                    },
                    y_speed: {
                        type: "linear",
                        position: "right",
                        title: { display: true, text: "Tốc độ (km/h)", color: "#10B981" },
                        ticks: { color: "#9CA3AF" },
                        grid: { drawOnChartArea: false }
                    }
                },
                plugins: {
                    legend: { labels: { color: "#F3F4F6" } }
                }
            }
        });

        // 2. Congestion Status Timeline Chart
        const ctx2 = document.getElementById("chart-congestion").getContext("2d");
        this.chartCongestion = new Chart(ctx2, {
            type: "line",
            data: {
                labels: [],
                datasets: [
                    {
                        label: "Trạng thái ùn tắc (0: Chưa đủ, 1: Thông thoáng, 2: Đông xe, 3: Ùn tắc)",
                        data: [],
                        borderColor: "#F59E0B",
                        backgroundColor: "rgba(245, 158, 11, 0.15)",
                        stepped: true,
                        fill: true
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { ticks: { color: "#9CA3AF" }, grid: { color: "rgba(255, 255, 255, 0.05)" } },
                    y: {
                        min: 0,
                        max: 3,
                        ticks: {
                            color: "#9CA3AF",
                            stepSize: 1,
                            callback: function(val) {
                                const map = { 0: "Chưa đủ DL", 1: "Thông thoáng", 2: "Đông xe", 3: "Ùn tắc" };
                                return map[val] || val;
                            }
                        },
                        grid: { color: "rgba(255, 255, 255, 0.05)" }
                    }
                },
                plugins: {
                    legend: { labels: { color: "#F3F4F6" } }
                }
            }
        });
    }

    reset() {
        if (!this.chartFlowSpeed || !this.chartCongestion) return;
        this.chartFlowSpeed.data.labels = [];
        this.chartFlowSpeed.data.datasets[0].data = [];
        this.chartFlowSpeed.data.datasets[1].data = [];
        this.chartFlowSpeed.update();

        this.chartCongestion.data.labels = [];
        this.chartCongestion.data.datasets[0].data = [];
        this.chartCongestion.update();
    }

    updateData(timelineData) {
        if (!this.chartFlowSpeed || !this.chartCongestion) return;
        const labels = timelineData.map(d => `${d.timestamp_sec.toFixed(1)}s`);
        const vehicleCounts = timelineData.map(d => d.vehicle_count_roi);
        const speeds = timelineData.map(d => d.avg_speed_kmh !== null ? d.avg_speed_kmh : null);

        const stateMap = { "Chưa đủ dữ liệu": 0, "Thông thoáng": 1, "Đông xe": 2, "Ùn tắc": 3 };
        const statusVals = timelineData.map(d => stateMap[d.traffic_status] || 0);

        this.chartFlowSpeed.data.labels = labels;
        this.chartFlowSpeed.data.datasets[0].data = vehicleCounts;
        this.chartFlowSpeed.data.datasets[1].data = speeds;
        this.chartFlowSpeed.update();

        this.chartCongestion.data.labels = labels;
        this.chartCongestion.data.datasets[0].data = statusVals;
        this.chartCongestion.update();
    }
}
