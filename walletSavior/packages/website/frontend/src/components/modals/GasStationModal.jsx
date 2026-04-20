import { MapPin, Fuel } from 'lucide-react';
import Modal from '../common/Modal';
import { fmt } from '../../utils/helpers';
import s from './GasStationModal.module.css';

export default function GasStationModal({ data, onClose }) {
  if (!data) return null;

  const name = data.name || '주유소';
  const addr = data.addr || data.address || '';
  const gasoline = data.gasoline ?? data.gasoline_price ?? null;
  const diesel = data.diesel ?? data.diesel_price ?? null;
  const distance = data.distance ?? data.dist ?? null;
  const brand = data.brand || data.company || '';

  return (
    <Modal isOpen onClose={onClose} title={name} size="sm">
      <div className={s.body}>
        <div className={s.badge}>
          <Fuel size={14} />
          주유소
        </div>

        {brand && (
          <div className={s.row}>
            <span className={s.label}>브랜드</span>
            <span>{brand}</span>
          </div>
        )}

        {gasoline != null && (
          <div className={s.row}>
            <span className={s.label}>휘발유</span>
            <span className={s.price}>{fmt(gasoline)}원/L</span>
          </div>
        )}

        {diesel != null && (
          <div className={s.row}>
            <span className={s.label}>경유</span>
            <span className={s.price}>{fmt(diesel)}원/L</span>
          </div>
        )}

        {distance != null && (
          <div className={s.row}>
            <span className={s.label}>거리</span>
            <span>{typeof distance === 'number' ? (distance < 1 ? `${Math.round(distance * 1000)}m` : `${distance.toFixed(1)}km`) : distance}</span>
          </div>
        )}

        {addr && (
          <div className={s.row}>
            <span className={s.label}>주소</span>
            <span className={s.addr}>{addr}</span>
          </div>
        )}

        <div className={s.actions}>
          {addr && (
            <a
              href={`https://map.naver.com/v5/search/${encodeURIComponent(name)}`}
              target="_blank"
              rel="noopener noreferrer"
              className={s.mapBtn}
            >
              <MapPin size={16} />
              지도에서 보기
            </a>
          )}
          <button className={s.closeBtn} onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </Modal>
  );
}
