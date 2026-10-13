import { useState } from 'react';
import { api } from './api';

interface Sample {
  available: boolean;
  reason: string | null;
  scope: string;
  observed_at: string | null;
  devices: {
    uuid: string; name: string;
    utilization_percent: number | null; used_vram_bytes: number | null;
    power_watts: number | null; temperature_celsius: number | null;
    unavailable_reasons: Record<string, string>;
  }[] | null;
}
const reading = (value: number | null, unit: string, scale = 1) => value === null ? 'N/A' : `${(value / scale).toFixed(1)} ${unit}`;

export function GpuDiagnostics() {
  const [sample, setSample] = useState<Sample | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const measure = async () => {
    setBusy(true); setError(''); setSample(null);
    try { setSample(await api<Sample>('/environment/gpu', {})); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <div>
    <button className="secondary" disabled={busy} onClick={() => void measure()}>{busy ? 'GPUを計測中…' : 'GPUの現在値を確認'}</button>
    <p className="fine-print">NVIDIA GPU全体の単発計測です。他アプリも含みます。PyTorchの導入やモデルの実行は不要です。</p>
    {error && <p role="alert">{error}</p>}
    {sample && <div role="status">
      <p>{sample.scope}</p>
      {sample.reason && <p>{sample.reason}</p>}
      {sample.observed_at && <p>取得時刻: {sample.observed_at}</p>}
      {sample.devices?.map(device => <div key={device.uuid}>
        <h3>{device.name}</h3><dl>
          <div><dt>GPU使用率</dt><dd>{reading(device.utilization_percent, '%')}</dd></div>
          <div><dt>GPU全体の使用メモリ</dt><dd>{reading(device.used_vram_bytes, 'MiB', 1048576)}</dd></div>
          <div><dt>消費電力</dt><dd>{reading(device.power_watts, 'W')}</dd></div>
          <div><dt>温度</dt><dd>{reading(device.temperature_celsius, '°C')}</dd></div>
        </dl>
        {Object.keys(device.unavailable_reasons).length > 0 && <p>一部の値はドライバーから取得できないためN/Aです。</p>}
      </div>)}
    </div>}
  </div>;
}
