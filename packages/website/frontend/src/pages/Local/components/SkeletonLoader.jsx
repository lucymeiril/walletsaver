import s from '../LocalPage.module.css';

export default function SkeletonLoader({ count = 5, message = '주변 업소를 찾고 있습니다...' }) {
  return (
    <div className={s.skeletonWrap}>
      <p className={s.skeletonMsg}>{message}</p>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={s.skeletonItem}>
          <div className={s.skeletonRank} />
          <div className={s.skeletonBody}>
            <div className={`${s.skeletonLine} ${s.skeletonLineWide}`} />
            <div className={`${s.skeletonLine} ${s.skeletonLineNarrow}`} />
          </div>
          <div className={s.skeletonPrice} />
        </div>
      ))}
    </div>
  );
}
