function resolveRatioAxisMax(values, fallback = 1) {
    const numericValues = (values || [])
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value));
    const maxValue = numericValues.length ? Math.max(...numericValues, fallback) : fallback;
    if (maxValue <= 1) return 1;
    return Number(Math.min(Math.ceil(maxValue * 10) / 10 + 0.1, 5).toFixed(1));
}

function renderObjectiveBar(elementId, payload) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const chart = echarts.init(el);
    const axisMax = resolveRatioAxisMax([
        ...(payload.quantitative || []),
        ...(payload.qualitative || []),
        payload.expected
    ]);
    chart.setOption({
        tooltip: { trigger: "axis" },
        legend: { data: ["定量达成度", "定性达成度", "期望值"] },
        grid: { left: 20, right: 20, top: 42, bottom: 20, containLabel: true },
        xAxis: { type: "category", data: payload.labels, axisTick: { show: false } },
        yAxis: { type: "value", max: axisMax, splitLine: { lineStyle: { color: "rgba(20,32,49,0.08)" } } },
        series: [
            { name: "定量达成度", type: "bar", data: payload.quantitative, itemStyle: { color: "#10213a", borderRadius: [10, 10, 0, 0] } },
            { name: "定性达成度", type: "bar", data: payload.qualitative, itemStyle: { color: "#0d7c6d", borderRadius: [10, 10, 0, 0] } },
            { name: "期望值", type: "line", data: payload.labels.map(() => payload.expected), itemStyle: { color: "#f97316" }, smooth: true, symbolSize: 8 }
        ]
    });
    bindChartResize(chart);
}

function renderGaugeChart(elementId, payload) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const chart = echarts.init(el);
    const axisMax = resolveRatioAxisMax([payload.value]);
    chart.setOption({
        series: [{
            type: "gauge",
            max: axisMax,
            progress: { show: true, width: 18 },
            axisLine: { lineStyle: { width: 18 } },
            detail: { valueAnimation: true, formatter: "{value}" },
            data: [{ value: Number(payload.value.toFixed(2)), name: payload.status }]
        }]
    });
    bindChartResize(chart);
}

function renderAssessmentBar(elementId, payload) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const chart = echarts.init(el);
    const axisMax = resolveRatioAxisMax(payload.values || []);
    chart.setOption({
        tooltip: { trigger: "axis" },
        grid: { left: 20, right: 20, top: 20, bottom: 20, containLabel: true },
        xAxis: { type: "category", data: payload.labels, axisTick: { show: false } },
        yAxis: { type: "value", max: axisMax, splitLine: { lineStyle: { color: "rgba(20,32,49,0.08)" } } },
        series: [{
            type: "bar",
            data: payload.values,
            itemStyle: { color: "#355c8d", borderRadius: [10, 10, 0, 0] }
        }]
    });
    bindChartResize(chart);
}

function renderDistributionBar(elementId, payload) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const chart = echarts.init(el);
    chart.setOption({
        tooltip: { trigger: "axis" },
        legend: {},
        grid: { left: 20, right: 20, top: 42, bottom: 20, containLabel: true },
        xAxis: { type: "category", data: payload.labels, axisTick: { show: false } },
        yAxis: { type: "value", splitLine: { lineStyle: { color: "rgba(20,32,49,0.08)" } } },
        series: payload.series.map((item, index) => ({
            ...item,
            type: "bar",
            itemStyle: { borderRadius: [8, 8, 0, 0] }
        }))
    });
    bindChartResize(chart);
}

function bindChartResize(chart) {
    window.addEventListener("resize", () => chart.resize());
}

if (window.mermaid) {
    mermaid.initialize({ startOnLoad: true, theme: "default" });
}

document.addEventListener("DOMContentLoaded", () => {
    const revealNodes = document.querySelectorAll(".reveal");
    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("revealed");
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.12 });

    revealNodes.forEach((node) => observer.observe(node));
});
