import s from './MartBadge.module.css';

// 마트 컬러 표준 — emart 노랑, 홈플 빨강, 롯데 파랑, 코스트코 진빨강
const MART_META = {
  emart:     { label: 'emart',     short: '이마트',   cls: s.emart },
  homeplus:  { label: 'homeplus',  short: '홈플러스', cls: s.homeplus },
  lottemart: { label: 'lottemart', short: '롯데마트', cls: s.lottemart },
  costco:    { label: 'costco',    short: '코스트코', cls: s.costco },
};

export const MART_CODES = Object.keys(MART_META);

export function martMeta(code) {
  return MART_META[code] || { label: code, short: code, cls: s.unknown };
}

export default function MartBadge({ code, missing = false, count }) {
  const meta = martMeta(code);
  return (
    <span
      className={`${s.badge} ${meta.cls} ${missing ? s.missing : ''}`}
      title={`${meta.short}${count != null ? ` (${count}건)` : ''}${missing ? ' — 수집 0건' : ''}`}
    >
      {meta.short}
      {count != null && <span className={s.count}>{count}</span>}
    </span>
  );
}

export function MartBadgeRow({ marts = [], showMissing = false }) {
  const set = new Set(marts);
  const codes = showMissing ? MART_CODES : marts;
  return (
    <div className={s.row}>
      {codes.map((c) => (
        <MartBadge key={c} code={c} missing={showMissing && !set.has(c)} />
      ))}
      {!showMissing && marts.length === 0 && (
        <span className={s.empty}>마트 정보 없음</span>
      )}
    </div>
  );
}
