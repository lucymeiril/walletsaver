import { useState, useEffect } from 'react';
import { Trash2, AlertTriangle, Database, RefreshCw, X, Loader } from 'lucide-react';
import { api } from '../../api/client';
import s from './Products.module.css';

const SOURCE_LABELS = {
  emart: '이마트', homeplus: '홈플러스', lottemart: '롯데마트',
  costco: '코스트코', government: '정부데이터',
};

export default function AdminResetModal({ open, onClose, onComplete }) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeAction, setActiveAction] = useState(null);
  const [confirmText, setConfirmText] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    if (open) {
      setActiveAction(null);
      setConfirmText('');
      setResult(null);
      setError(null);
      fetchSummary();
    }
  }, [open]);

  const fetchSummary = async () => {
    setLoading(true);
    try {
      const data = await api.getDataSummary();
      setSummary(data);
    } catch (err) {
      setError(`데이터 요약 로드 실패: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAction = async (action, payload) => {
    setProcessing(true);
    setError(null);
    setResult(null);
    try {
      let res;
      if (action === 'reset-source') {
        res = await api.resetSource(payload.source, payload.confirm);
      } else if (action === 'reset-products') {
        res = await api.resetProducts(payload.confirm);
      } else if (action === 'reset-all') {
        res = await api.resetAll(payload.confirm);
      }
      setResult(res);
      setActiveAction(null);
      setConfirmText('');
      fetchSummary();
      if (onComplete) onComplete();
    } catch (err) {
      setError(err.message);
    } finally {
      setProcessing(false);
    }
  };

  if (!open) return null;

  const getExpectedConfirm = () => {
    if (!activeAction) return '';
    if (activeAction.type === 'reset-source') return `DELETE_${activeAction.source.toUpperCase()}`;
    if (activeAction.type === 'reset-products') return 'DELETE_ALL_PRODUCTS';
    if (activeAction.type === 'reset-all') return 'RESET_ALL_DATA';
    return '';
  };

  const isConfirmValid = confirmText === getExpectedConfirm();

  return (
    <div className={s.overlay} onClick={onClose}>
      <div className={s.modal} style={{ maxWidth: 720 }} onClick={e => e.stopPropagation()}>
        <div className={s.modalHeader}>
          <h3><Database size={18} style={{ marginRight: 8, verticalAlign: 'middle' }} />DB 관리 · 데이터 초기화</h3>
          <button onClick={onClose}><X size={18} /></button>
        </div>

        <div style={{ padding: 24 }}>
          {/* 성공 결과 */}
          {result && (
            <div style={{
              padding: '12px 16px', marginBottom: 16, borderRadius: 'var(--radius-sm)',
              background: 'rgba(52,211,153,.1)', border: '1px solid rgba(52,211,153,.25)',
              color: 'var(--green)', fontSize: 'var(--fs-sm)',
            }}>
              ✅ 삭제 완료 — 총 {result.deleted?.total ?? Object.values(result.deleted || {}).reduce((a, b) => typeof b === 'number' ? a + b : a, 0)}건 삭제됨
            </div>
          )}

          {/* 에러 */}
          {error && (
            <div style={{
              padding: '12px 16px', marginBottom: 16, borderRadius: 'var(--radius-sm)',
              background: 'rgba(248,113,113,.08)', border: '1px solid rgba(248,113,113,.2)',
              color: 'var(--red)', fontSize: 'var(--fs-sm)',
            }}>
              <AlertTriangle size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
              {error}
            </div>
          )}

          {loading && <div style={{ textAlign: 'center', padding: 40, color: 'var(--text3)' }}>데이터 요약 로딩 중...</div>}

          {!loading && summary && !activeAction && (
            <>
              {/* 데이터 요약 */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text3)', marginBottom: 8 }}>현재 데이터 현황</div>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
                  <SummaryBadge label="상품" count={summary.total_products} />
                  <SummaryBadge label="카테고리" count={summary.total_categories} />
                  <SummaryBadge label="키워드" count={summary.total_keywords} />
                </div>
              </div>

              {/* 소스별 삭제 */}
              <ActionSection
                icon={<RefreshCw size={16} />}
                title="소스별 데이터 삭제"
                description="특정 소스의 가격 데이터만 삭제합니다. 상품은 유지됩니다."
                level="warning"
              >
                {summary.sources?.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
                    {summary.sources.map(src => (
                      <div key={src.source} style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '8px 12px', borderRadius: 'var(--radius-sm)',
                        background: 'var(--glass2)',
                      }}>
                        <span style={{ fontSize: 'var(--fs-sm)' }}>
                          {SOURCE_LABELS[src.source] || src.source}
                          <span style={{ color: 'var(--text3)', marginLeft: 8, fontSize: 'var(--fs-xs)' }}>
                            상품 {src.product_count}개 · 가격 {src.price_count}건
                          </span>
                        </span>
                        <button
                          style={{
                            padding: '4px 12px', borderRadius: 'var(--radius-sm)', fontSize: 'var(--fs-xs)',
                            background: 'rgba(251,191,36,.1)', color: 'var(--yellow)', fontWeight: 600,
                          }}
                          onClick={() => setActiveAction({ type: 'reset-source', source: src.source })}
                        >
                          삭제
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text3)', marginTop: 8 }}>소스 데이터 없음</div>
                )}
              </ActionSection>

              {/* 전체 상품 초기화 */}
              <ActionSection
                icon={<Trash2 size={16} />}
                title="전체 상품 초기화"
                description="모든 상품과 가격 데이터를 삭제합니다. 카테고리·키워드는 보존됩니다."
                level="danger"
              >
                <button
                  style={{
                    marginTop: 10, padding: '8px 16px', borderRadius: 'var(--radius-sm)', fontSize: 'var(--fs-sm)',
                    background: 'rgba(248,113,113,.1)', color: 'var(--red)', fontWeight: 600,
                    display: 'flex', alignItems: 'center', gap: 6,
                  }}
                  onClick={() => setActiveAction({ type: 'reset-products' })}
                >
                  <Trash2 size={14} /> 전체 상품 삭제
                </button>
              </ActionSection>

              {/* DB 완전 초기화 */}
              <ActionSection
                icon={<AlertTriangle size={16} />}
                title="DB 완전 초기화"
                description="모든 데이터(상품·카테고리·키워드)를 삭제합니다. 빈 데이터베이스로 돌아갑니다."
                level="critical"
              >
                <button
                  style={{
                    marginTop: 10, padding: '8px 16px', borderRadius: 'var(--radius-sm)', fontSize: 'var(--fs-sm)',
                    background: 'rgba(248,113,113,.15)', color: 'var(--red)', fontWeight: 700,
                    display: 'flex', alignItems: 'center', gap: 6, border: '1px solid rgba(248,113,113,.3)',
                  }}
                  onClick={() => setActiveAction({ type: 'reset-all' })}
                >
                  <AlertTriangle size={14} /> DB 완전 초기화
                </button>
              </ActionSection>
            </>
          )}

          {/* 확인 입력 단계 */}
          {activeAction && (
            <ConfirmStep
              action={activeAction}
              expectedConfirm={getExpectedConfirm()}
              confirmText={confirmText}
              setConfirmText={setConfirmText}
              isValid={isConfirmValid}
              processing={processing}
              onConfirm={() => handleAction(activeAction.type, {
                source: activeAction.source,
                confirm: confirmText,
              })}
              onCancel={() => { setActiveAction(null); setConfirmText(''); setError(null); }}
            />
          )}
        </div>
      </div>
    </div>
  );
}


function SummaryBadge({ label, count }) {
  return (
    <div style={{
      padding: '8px 14px', borderRadius: 'var(--radius-sm)',
      background: 'var(--surface)', border: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column', gap: 2, minWidth: 80,
    }}>
      <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text3)' }}>{label}</span>
      <span style={{ fontSize: 'var(--fs-lg)', fontWeight: 700 }}>{count ?? 0}</span>
    </div>
  );
}


function ActionSection({ icon, title, description, level, children }) {
  const borderColor = level === 'critical'
    ? 'rgba(248,113,113,.3)' : level === 'danger'
    ? 'rgba(248,113,113,.15)' : 'rgba(251,191,36,.15)';
  return (
    <div style={{
      padding: 16, marginBottom: 12, borderRadius: 'var(--radius-sm)',
      border: `1px solid ${borderColor}`, background: 'var(--glass2)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        {icon}
        <span style={{ fontWeight: 600, fontSize: 'var(--fs-sm)' }}>{title}</span>
      </div>
      <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text3)' }}>{description}</div>
      {children}
    </div>
  );
}


function ConfirmStep({ action, expectedConfirm, confirmText, setConfirmText, isValid, processing, onConfirm, onCancel }) {
  const actionLabel = action.type === 'reset-source'
    ? `"${SOURCE_LABELS[action.source] || action.source}" 소스 데이터 삭제`
    : action.type === 'reset-products'
    ? '전체 상품 데이터 삭제'
    : 'DB 완전 초기화';

  const warningText = action.type === 'reset-source'
    ? `"${action.source}" 소스의 모든 가격 데이터가 영구 삭제됩니다.`
    : action.type === 'reset-products'
    ? '모든 상품과 가격 데이터가 영구 삭제됩니다. 카테고리와 키워드는 보존됩니다.'
    : '카테고리, 키워드 포함 모든 데이터가 영구 삭제됩니다. 이 작업은 되돌릴 수 없습니다.';

  return (
    <div style={{ padding: 16, borderRadius: 'var(--radius-sm)', border: '1px solid rgba(248,113,113,.3)', background: 'rgba(248,113,113,.04)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <AlertTriangle size={18} style={{ color: 'var(--red)' }} />
        <span style={{ fontWeight: 700, fontSize: 'var(--fs-base)', color: 'var(--red)' }}>{actionLabel}</span>
      </div>
      <p style={{ fontSize: 'var(--fs-sm)', color: 'var(--text2)', marginBottom: 16, lineHeight: 1.5 }}>{warningText}</p>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 'var(--fs-sm)', color: 'var(--text2)' }}>
        확인을 위해 <code style={{
          padding: '2px 6px', borderRadius: 4, background: 'rgba(248,113,113,.1)',
          color: 'var(--red)', fontWeight: 600, fontSize: 'var(--fs-sm)',
        }}>{expectedConfirm}</code> 을 입력하세요:
        <input
          type="text"
          value={confirmText}
          onChange={e => setConfirmText(e.target.value)}
          placeholder={expectedConfirm}
          autoFocus
          style={{
            padding: '8px 12px', borderRadius: 'var(--radius-sm)',
            border: `1px solid ${isValid ? 'var(--green)' : 'var(--border)'}`,
            background: 'var(--bg2)', color: 'var(--text)', fontSize: 'var(--fs-sm)',
            fontFamily: 'monospace',
          }}
        />
      </label>

      <div style={{ display: 'flex', gap: 10, marginTop: 16, justifyContent: 'flex-end' }}>
        <button
          onClick={onCancel}
          disabled={processing}
          style={{
            padding: '8px 20px', borderRadius: 'var(--radius-sm)',
            background: 'var(--glass2)', color: 'var(--text)', fontSize: 'var(--fs-sm)',
          }}
        >
          취소
        </button>
        <button
          onClick={onConfirm}
          disabled={!isValid || processing}
          style={{
            padding: '8px 20px', borderRadius: 'var(--radius-sm)',
            background: isValid ? 'var(--red)' : 'var(--glass2)',
            color: isValid ? '#fff' : 'var(--text3)',
            fontWeight: 600, fontSize: 'var(--fs-sm)',
            opacity: processing ? 0.6 : 1,
            display: 'flex', alignItems: 'center', gap: 6,
          }}
        >
          {processing && <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />}
          {processing ? '삭제 중...' : '삭제 실행'}
        </button>
      </div>
    </div>
  );
}
