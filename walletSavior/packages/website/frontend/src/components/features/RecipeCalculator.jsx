import { useState, useEffect } from 'react';
import { fmt } from '../../utils/helpers';
import s from './RecipeCalculator.module.css';

function calcRecipeCost(recipe) {
  const total = recipe.ingredients.reduce((s, i) => s + i.cost, 0);
  const savings = recipe.eatingOut - total;
  const pct = Math.round((savings / recipe.eatingOut) * 100);
  return { total, savings, pct };
}

export default function RecipeCalculator() {
  const [recipes, setRecipes] = useState([]);
  const [selected, setSelected] = useState(0);
  const [loading, setLoading] = useState(true);

  // 레시피 비교 데이터를 API에서 조회
  useEffect(() => {
    fetch('/api/recipes/compare').then(r => r.json())
      .then(res => setRecipes(res.data || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text3)' }}>로딩 중...</div>;
  if (recipes.length === 0) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text3)' }}>레시피 데이터가 없습니다</div>;

  const recipe = recipes[selected];
  if (!recipe) return null;
  const { total, savings, pct } = calcRecipeCost(recipe);

  return (
    <section className={s.sec}>
      <h2 className={s.title}>🍳 집에서 해먹으면 얼마?</h2>
      <p className={s.sub}>외식 vs 집밥 비용 비교 — 재료비는 실시간 시세 기반</p>

      <div className={s.tabs}>
        {recipes.map((r, i) => (
          <button key={r.name} className={`${s.tab} ${selected === i ? s.tabActive : ''}`} onClick={() => setSelected(i)}>
            {r.icon} {r.name}
          </button>
        ))}
      </div>

      <div className={s.compare}>
        <div className={`${s.box} ${s.eatOut}`}>
          <span className={s.label}>🍽️ 외식하면</span>
          <span className={s.bigPrice}>{fmt(recipe.eatingOut)}원</span>
          <span className={s.perServing}>1인분 기준</span>
        </div>
        <div className={s.vs}>VS</div>
        <div className={`${s.box} ${s.cookHome}`}>
          <span className={s.label}>🏠 집에서 만들면</span>
          <span className={s.bigPrice}>{fmt(total)}원</span>
          <span className={s.perServing}>{recipe.servings}인분 재료비</span>
        </div>
      </div>

      <div className={s.savings}>
        <span className={s.savingsIcon}>💰</span>
        <div>
          <strong>{fmt(savings)}원 절약!</strong>
          <span className={s.savingsPct}>({pct}% 저렴)</span>
        </div>
      </div>

      <div className={s.ingredients}>
        <h4>재료 상세</h4>
        <div className={s.ingGrid}>
          {recipe.ingredients.map((ing) => (
            <div key={`${ing.name}-${ing.amount}`} className={s.ingItem}>
              <span className={s.ingName}>{ing.name}</span>
              <span className={s.ingAmount}>{ing.amount}</span>
              <span className={s.ingCost}>{fmt(ing.cost)}원</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
