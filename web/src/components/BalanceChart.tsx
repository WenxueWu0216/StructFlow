export interface Series {
  label: string;
  color: string;
  values: number[];
}

interface Props {
  series: Series[];
  width?: number;
  height?: number;
}

const PAD = { top: 12, right: 16, bottom: 32, left: 64 };

/** SVG path for values plotted at x = index + 1 (month), y scaled to [0, yMax]. */
export function linePath(
  values: number[],
  xMax: number,
  yMax: number,
  innerWidth: number,
  innerHeight: number,
): string {
  if (values.length === 0 || xMax <= 0 || yMax <= 0) return "";
  return values
    .map((v, i) => {
      const x = ((i + 1) / xMax) * innerWidth;
      const y = innerHeight - (v / yMax) * innerHeight;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join("");
}

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function BalanceChart({ series, width = 720, height = 280 }: Props) {
  const innerW = width - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const xMax = Math.max(1, ...series.map((s) => s.values.length));
  const yMax = Math.max(1, ...series.flatMap((s) => s.values));
  const yearTicks = Array.from({ length: Math.floor(xMax / 60) + 1 }, (_, i) => i * 60);
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);

  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Outstanding balance by month for each scenario"
      >
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {yTicks.map((v) => {
            const y = innerH - (v / yMax) * innerH;
            return (
              <g key={v}>
                <line className="grid" x1={0} x2={innerW} y1={y} y2={y} />
                <text className="tick" x={-8} y={y} textAnchor="end" dominantBaseline="middle">
                  {compact.format(v)}
                </text>
              </g>
            );
          })}
          {yearTicks.map((m) => (
            <text key={m} className="tick" x={(m / xMax) * innerW} y={innerH + 18} textAnchor="middle">
              {m / 12}y
            </text>
          ))}
          {series.map((s) => (
            <path
              key={s.label}
              d={linePath(s.values, xMax, yMax, innerW, innerH)}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
            >
              <title>{s.label}</title>
            </path>
          ))}
        </g>
      </svg>
      <figcaption className="legend">
        {series.map((s) => (
          <span key={s.label}>
            <i style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
