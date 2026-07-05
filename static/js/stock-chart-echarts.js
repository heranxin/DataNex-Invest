/**
 * 数境智投 — ECharts 行情图（折线 / K 线 + 成交量）
 */
window.StockChartEcharts = {
    init(containerId, options) {
        const el = document.getElementById(containerId);
        if (!el || typeof echarts === 'undefined') return null;

        const chart = echarts.init(el, null, { renderer: 'canvas' });
        const state = { chart, mode: 'line', series: [], name: '', code: '' };

        function buildOption(mode) {
            const dates = state.series.map((d) => d.date);
            const closes = state.series.map((d) => d.close);
            const volumes = state.series.map((d) => d.volume || 0);

            const upColor = '#EF4444';
            const downColor = '#10B981';
            const teal = '#00B5AD';

            const baseGrid = { left: 56, right: 24, top: 48, bottom: 72 };

            if (mode === 'candle') {
                const ohlc = state.series.map((d) => [d.open, d.close, d.low, d.high]);
                return {
                    backgroundColor: 'transparent',
                    animation: true,
                    tooltip: {
                        trigger: 'axis',
                        axisPointer: { type: 'cross' },
                        backgroundColor: 'rgba(255,255,255,0.96)',
                        borderColor: '#99F6E4',
                        textStyle: { color: '#134E4A', fontSize: 12 },
                        formatter: function (params) {
                            if (!params || !params.length) return '';
                            const i = params[0].dataIndex;
                            const row = state.series[i];
                            let html = params[0].axisValue + '<br/>';
                            params.forEach(function (p) {
                                if (p.seriesName === 'K线' && row) {
                                    html += '开 ' + row.open + ' 收 ' + row.close +
                                        ' 低 ' + row.low + ' 高 ' + row.high + '<br/>';
                                } else if (p.seriesName === '成交量') {
                                    const v = p.value || 0;
                                    const wan = v >= 10000 ? (v / 10000).toFixed(2) + ' 万手' : v + ' 手';
                                    html += '成交量 ' + wan + '<br/>';
                                }
                            });
                            return html;
                        },
                    },
                    legend: {
                        top: 8,
                        itemGap: 20,
                        icon: 'none',
                        data: ['K线', '成交量'],
                        textStyle: {
                            color: '#64748B',
                            fontSize: 11,
                            rich: {
                                rb: { width: 10, height: 10, backgroundColor: upColor, borderRadius: 2 },
                                gb: { width: 10, height: 10, backgroundColor: downColor, borderRadius: 2 },
                            },
                        },
                        formatter: function (name) {
                            if (name === '成交量') {
                                return '{rb|}{gb|} 成交量（红涨 / 绿跌）';
                            }
                            return '{rb|}{gb|} K线';
                        },
                    },
                    grid: [
                        { ...baseGrid, height: '52%' },
                        { left: 56, right: 24, top: '68%', height: '18%' },
                    ],
                    xAxis: [
                        { type: 'category', data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#CBD5E1' } }, axisLabel: { color: '#94A3B8', fontSize: 10 } },
                        { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false } },
                    ],
                    yAxis: [
                        { scale: true, splitLine: { lineStyle: { color: '#F1F5F9' } }, axisLabel: { color: '#94A3B8' } },
                        { scale: true, gridIndex: 1, splitNumber: 2,
                          axisLabel: {
                              show: true,
                              color: '#94A3B8',
                              fontSize: 9,
                              formatter: function (v) {
                                  return v >= 10000 ? (v / 10000).toFixed(0) + '万' : v;
                              },
                          },
                          splitLine: { show: false } },
                    ],
                    dataZoom: [
                        { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
                        { type: 'slider', xAxisIndex: [0, 1], start: 60, end: 100, bottom: 12, height: 18, borderColor: '#E2E8F0', fillerColor: 'rgba(0,181,173,0.15)', handleStyle: { color: teal } },
                    ],
                    series: [
                        {
                            name: 'K线',
                            type: 'candlestick',
                            data: ohlc,
                            itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor },
                        },
                        {
                            name: '成交量',
                            type: 'bar',
                            xAxisIndex: 1,
                            yAxisIndex: 1,
                            data: volumes,
                            color: upColor,
                            itemStyle: {
                                color: (p) => {
                                    const row = state.series[p.dataIndex];
                                    return row && row.close >= row.open ? upColor : downColor;
                                },
                            },
                        },
                    ],
                };
            }

            return {
                backgroundColor: 'transparent',
                animation: true,
                tooltip: {
                    trigger: 'axis',
                    backgroundColor: 'rgba(255,255,255,0.96)',
                    borderColor: '#99F6E4',
                    textStyle: { color: '#134E4A' },
                },
                grid: { ...baseGrid, bottom: 80 },
                xAxis: {
                    type: 'category',
                    data: dates,
                    boundaryGap: false,
                    axisLine: { lineStyle: { color: '#CBD5E1' } },
                    axisLabel: { color: '#94A3B8', fontSize: 10 },
                },
                yAxis: {
                    scale: true,
                    splitLine: { lineStyle: { color: '#F1F5F9' } },
                    axisLabel: { color: '#94A3B8' },
                },
                dataZoom: [
                    { type: 'inside', start: 50, end: 100 },
                    { type: 'slider', start: 50, end: 100, bottom: 12, height: 18, borderColor: '#E2E8F0', fillerColor: 'rgba(0,181,173,0.15)', handleStyle: { color: teal } },
                ],
                series: [{
                    name: '收盘价',
                    type: 'line',
                    data: closes,
                    smooth: true,
                    symbol: 'none',
                    lineStyle: { width: 2, color: teal },
                    areaStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(0,181,173,0.35)' },
                            { offset: 1, color: 'rgba(0,181,173,0.02)' },
                        ]),
                    },
                }],
            };
        }

        state.setData = function (payload) {
            state.series = payload.series || [];
            state.name = payload.name || '';
            state.code = payload.code || '';
            chart.setOption(buildOption(state.mode), true);
        };

        state.setMode = function (mode) {
            state.mode = mode === 'candle' ? 'candle' : 'line';
            chart.setOption(buildOption(state.mode), true);
        };

        window.addEventListener('resize', () => chart.resize());
        if (options && options.onReady) options.onReady(state);
        return state;
    },
};
