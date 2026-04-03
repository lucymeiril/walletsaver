import { useState, useRef, useEffect } from 'react';
import { Share2, Link, MessageCircle, ExternalLink } from 'lucide-react';
import useStore from '../../stores/appStore';
import s from './ShareButton.module.css';

export default function ShareButton({ title, text, url, price, type = 'icon' }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const { addToast } = useStore();

  useEffect(() => {
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    if (open) document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  const shareUrl = url || window.location.href;
  const shareText = text || title || '';

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      addToast('링크가 복사되었습니다!', 'success');
    } catch {
      addToast('링크 복사에 실패했습니다', 'info');
    }
    setOpen(false);
  };

  const shareKakao = () => {
    // TODO: Kakao SDK 초기화 후 활성화
    // window.Kakao?.Link?.sendDefault({
    //   objectType: 'feed',
    //   content: {
    //     title: title || '지갑지키미',
    //     description: shareText,
    //     imageUrl: '',
    //     link: { mobileWebUrl: shareUrl, webUrl: shareUrl },
    //   },
    //   buttons: [{ title: '자세히 보기', link: { mobileWebUrl: shareUrl, webUrl: shareUrl } }],
    // });
    addToast('카카오톡 SDK 연동 준비 중입니다', 'info');
    setOpen(false);
  };

  const shareTwitter = () => {
    window.open(
      `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(shareUrl)}`,
      '_blank',
      'width=550,height=420'
    );
    setOpen(false);
  };

  return (
    <div className={s.wrap} ref={ref}>
      <button
        className={type === 'button' ? s.shareBtn : s.shareIcon}
        onClick={() => setOpen(!open)}
        aria-label="공유하기"
      >
        <Share2 size={type === 'button' ? 16 : 15} />
        {type === 'button' && <span>공유</span>}
      </button>
      {open && (
        <div className={s.popup}>
          <button className={s.option} onClick={copyLink}>
            <Link size={16} /> 링크 복사
          </button>
          <button className={s.option} onClick={shareKakao}>
            <MessageCircle size={16} /> 카카오톡 공유
          </button>
          <button className={s.option} onClick={shareTwitter}>
            <ExternalLink size={16} /> 트위터 공유
          </button>
        </div>
      )}
    </div>
  );
}
