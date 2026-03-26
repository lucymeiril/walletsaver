import { useState } from 'react';
import { RECIPES, calcRecipeCost, fmt } from '../../data/mockData';
import s from './RecipeCalculator.module.css';

export default function RecipeCalculator() {
  const [selected, setSelected] = useState(0);
  const recipe = RECIPES[selected];
  const { total, savings, pct } = calcRecipeCost(recipe);

  return (
    <section className={s.sec}>
      <h2 className={s.title}>🍳 집에서 해먹으면 얼마?</h2>
      <p className={s.sub}>외식 vs 집밥 비용 비교 — 재료비는 실시간 시세 기반</p>

      <div className={s.tabs}>
        {RECIPES.map((r, i) => (
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
          {recipe.ingredients.map((ing, i) => (
            <div key={i} className={s.ingItem}>
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
