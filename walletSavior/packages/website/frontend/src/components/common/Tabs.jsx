import { useState, useRef, useEffect } from 'react';
import s from './Tabs.module.css';

export default function Tabs({
  tabs = [],
  defaultTab,
  onChange,
  className = '',
}) {
  const [activeId, setActiveId] = useState(defaultTab || tabs[0]?.id);
  const [indicator, setIndicator] = useState({ left: 0, width: 0 });
  const tabsRef = useRef({});
  const containerRef = useRef(null);

  useEffect(() => {
    const el = tabsRef.current[activeId];
    if (el) {
      const container = containerRef.current;
      const containerRect = container.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      setIndicator({
        left: elRect.left - containerRect.left,
        width: elRect.width,
      });
    }
  }, [activeId]);

  const handleTabClick = (id) => {
    setActiveId(id);
    if (onChange) onChange(id);
  };

  const activeTab = tabs.find((t) => t.id === activeId);

  return (
    <div className={`${s.wrapper} ${className}`}>
      <div className={s.tabList} ref={containerRef} role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            ref={(el) => { tabsRef.current[tab.id] = el; }}
            role="tab"
            aria-selected={tab.id === activeId}
            className={`${s.tab} ${tab.id === activeId ? s.active : ''}`}
            onClick={() => handleTabClick(tab.id)}
          >
            {tab.label}
          </button>
        ))}
        <div
          className={s.indicator}
          style={{ left: indicator.left, width: indicator.width }}
        />
      </div>
      <div className={s.panel} role="tabpanel">
        {activeTab?.content}
      </div>
    </div>
  );
}
