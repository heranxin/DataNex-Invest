/**
 * 回报率回测 — ECharts 动态曲线
 */
(function (global) {
    var upColor = '#DC2626';
    var downColor = '#16A34A';
    var primary = '#00B5AD';

    function init(container) {
        if (!container || typeof echarts === 'undefined') return null;
        var chart = echarts.init(container, null, { renderer: 'canvas' });
        var onResize = function () {
            if (chart && !chart.isDisposed()) chart.resize();
        };
        window.addEventListener('resize', onResize);
        chart.__rrOnResize = onResize;
        return chart;
    }

    function render(chart, data) {
        if (!chart || !data || !data.points || !data.points.length) return;

        var dates = data.points.map(function (p) { return p.date; });
        var returns = data.points.map(function (p) { return p.return_pct; });
        var lastRet = returns[returns.length - 1];
        var lineColor = lastRet >= 0 ? upColor : downColor;
        var areaTop = lastRet >= 0 ? 'rgba(220, 38, 38, 0.22)' : 'rgba(22, 163, 74, 0.22)';
        var areaBottom = 'rgba(255, 255, 255, 0)';
        var manyDates = dates.length > 8;

        chart.setOption({
            animation: true,
            animationDuration: 800,
            animationEasing: 'cubicOut',
            grid: {
                left: 48,
                right: 28,
                top: 52,
                bottom: manyDates ? 64 : 48,
                containLabel: true,
            },
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(255,255,255,0.96)',
                borderColor: '#99F6E4',
                textStyle: { color: '#134E4A', fontSize: 12 },
                formatter: function (params) {
                    var p = params[0];
                    var idx = p.dataIndex;
                    var pt = data.points[idx];
                    var sign = pt.return_pct > 0 ? '+' : '';
                    return '<strong>' + pt.date + '</strong><br/>' +
                        '收盘 ' + pt.close + ' 元<br/>' +
                        '累计回报 <span style="color:' + (pt.return_pct >= 0 ? upColor : downColor) + '">' +
                        sign + pt.return_pct.toFixed(2) + '%</span>';
                },
            },
            xAxis: {
                type: 'category',
                data: dates,
                boundaryGap: false,
                axisLine: { lineStyle: { color: '#CBD5E1' } },
                axisTick: { alignWithLabel: true },
                axisLabel: {
                    color: '#64748B',
                    fontSize: 11,
                    rotate: manyDates ? 35 : 0,
                    interval: dates.length > 15 ? Math.floor(dates.length / 8) : 0,
                },
            },
            yAxis: {
                type: 'value',
                name: '回报率 (%)',
                nameTextStyle: { color: '#94A3B8', fontSize: 11, padding: [0, 0, 8, 0] },
                axisLabel: {
                    color: '#64748B',
                    formatter: function (v) { return v.toFixed(1) + '%'; },
                },
                splitLine: { lineStyle: { type: 'dashed', color: '#E2E8F0' } },
            },
            series: [
                {
                    name: '累计回报率',
                    type: 'line',
                    smooth: 0.3,
                    symbol: 'circle',
                    symbolSize: function (val, params) {
                        var i = params.dataIndex;
                        if (i === 0 || i === returns.length - 1) return 9;
                        return dates.length > 20 ? 0 : 4;
                    },
                    showSymbol: true,
                    data: returns,
                    lineStyle: { width: 2.5, color: lineColor },
                    itemStyle: {
                        color: function (p) {
                            if (p.dataIndex === 0) return '#EF4444';
                            if (p.dataIndex === returns.length - 1) return primary;
                            return lineColor;
                        },
                        borderWidth: 2,
                        borderColor: '#fff',
                    },
                    areaStyle: {
                        origin: 'auto',
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: areaTop },
                            { offset: 1, color: areaBottom },
                        ]),
                    },
                    markLine: {
                        silent: true,
                        symbol: 'none',
                        lineStyle: { color: '#94A3B8', type: 'dashed', width: 1 },
                        data: [{ yAxis: 0, label: { formatter: '0% 盈亏线', color: '#94A3B8', fontSize: 10 } }],
                    },
                    markPoint: {
                        symbol: 'roundRect',
                        symbolSize: [72, 36],
                        data: [
                            {
                                name: '买入',
                                coord: [dates[0], returns[0]],
                                value: '买入 0%',
                                itemStyle: { color: '#EF4444' },
                                label: { color: '#fff', fontSize: 10, fontWeight: 'bold' },
                            },
                            {
                                name: '最新',
                                coord: [dates[dates.length - 1], lastRet],
                                value: '最新 ' + (lastRet >= 0 ? '+' : '') + lastRet.toFixed(2) + '%',
                                itemStyle: { color: primary },
                                label: { color: '#fff', fontSize: 10, fontWeight: 'bold' },
                            },
                        ],
                    },
                },
            ],
        }, true);

        requestAnimationFrame(function () {
            chart.resize();
            requestAnimationFrame(function () { chart.resize(); });
        });
    }

    global.ReturnRateChart = { init: init, render: render };
})(window);
