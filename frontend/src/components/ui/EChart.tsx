import React, { useEffect, useRef } from "react";
import * as echarts from "echarts";

/** ECharts 容器：接收 option，自适应尺寸，随数据变化刷新。 */
export function EChart({ option, height = 280, className }: { option: any; height?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chart.current || !option) return;
    chart.current.setOption(option, true);
    setTimeout(() => chart.current?.resize(), 40);
  }, [option]);

  return <div ref={ref} style={{ height }} className={className} />;
}
