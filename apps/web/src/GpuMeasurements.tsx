interface Statistic { samples: number; mean: number | null; observed_max: number | null; }
interface Measurement { scope: string; samples: number; failed_samples: number; reason?: string | null; windows_without_samples?: number; devices: { uuid: string; name: string; unavailable_reasons?: Record<string, string>; metrics: Record<string, Statistic> }[]; }
const labels: Record<string, [string, number, string]> = { utilization_percent: ['使用率', 1, '%'], used_vram_bytes: ['使用VRAM', 1048576, 'MiB'], power_watts: ['電力', 1, 'W'], temperature_celsius: ['温度', 1, '°C'] };

export function GpuMeasurements({ value }: { value?: unknown }) {
  if (!value || typeof value !== 'object' || !('devices' in value)) return null;
  const data = value as Measurement;
  return <section className="panel"><h3>GPU使用状況（ホスト全体）</h3><p>{data.samples}サンプル · 取得失敗 {data.failed_samples}回{data.windows_without_samples !== undefined && ` · サンプルなし ${data.windows_without_samples}問`}</p>{data.reason && <p>{data.reason}</p>}{data.devices.map(device => <div key={device.uuid}><h4>{device.name}</h4><div className="table-scroll"><table><thead><tr><th>指標</th><th>標本平均</th><th>観測最大値</th><th>標本数</th></tr></thead><tbody>{Object.entries(labels).map(([key, [label, scale, unit]]) => { const stat = device.metrics[key]; const format = (v: number | null | undefined) => v == null ? 'N/A' : `${(v / scale).toFixed(1)} ${unit}`; return <tr key={key}><td>{label}</td><td>{format(stat?.mean)}</td><td>{format(stat?.observed_max)}</td><td>{stat?.samples ?? 0}</td></tr>; })}</tbody></table></div>{Object.entries(device.unavailable_reasons ?? {}).map(([key, reason]) => <p className="fine-print" key={key}>{labels[key]?.[0] ?? key}: {reason}</p>)}</div>)}<p className="fine-print">{data.scope}</p></section>;
}
