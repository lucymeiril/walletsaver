export function StoredSpecification({ variant }) {
  const display = typeof variant.display_unit === 'string' ? variant.display_unit.trim() : '';
  const q = variant.package_quantity;
  const unit = typeof variant.package_unit === 'string' ? variant.package_unit.trim() : '';
  const knownScalar = typeof q === 'number' && Number.isFinite(q) && q > 0 && unit;
  return <>
    {display && <p>저장된 표시 규격: {display}</p>}
    <p>저장된 규격값: {knownScalar ? `${q}${unit}` : '미확인'}
      {knownScalar && Number.isInteger(variant.bundle_count) && variant.bundle_count > 0 ? ` ×${variant.bundle_count}` : ''}
    </p>
    <p>묶음·세트 저장값은 실제 용기·낱개 수를 뜻하지 않습니다.</p>
    {Array.isArray(variant.quantity_components) && variant.quantity_components.length > 0 && <div>
      <strong>검증된 선언 구성</strong>
      <ul>{variant.quantity_components.map((c, i) => <li key={i}>
        {c.identity || c.presentation || '구성명 미확인'} ·
        {typeof c.quantity === 'number' && Number.isFinite(c.quantity) && c.unit ? ` ${c.quantity}${c.unit}` : ' 양 미확인'} ·
        {typeof c.count === 'number' && Number.isFinite(c.count) ? ` 구성 수 ${c.count}` : ' 구성 수 미확인'}
        {c.amount_scope ? ` · 범위 ${c.amount_scope}` : ''}
      </li>)}</ul>
    </div>}
    {variant.quantity_comparison_reason && <p>수량 비교 보류: {variant.quantity_comparison_reason}</p>}
    {variant.attributes && Object.keys(variant.attributes).length > 0 && <details>
      <summary>저장된 규격 검토 메타데이터</summary>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(variant.attributes, null, 2)}</pre>
    </details>}
  </>;
}

export function CatalogPagination({ data, page, setPage }) {
  return <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
    <span>총 {data.total.toLocaleString()}개 · {page} / {Math.max(1, data.total_pages)}</span>
    <button disabled={page <= 1} onClick={() => setPage(page - 1)}>이전</button>
    <button disabled={page >= data.total_pages} onClick={() => setPage(page + 1)}>다음</button>
  </div>;
}
