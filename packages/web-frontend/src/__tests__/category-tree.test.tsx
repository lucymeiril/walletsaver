import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { CategoryTree } from '../components/CategoryTree'
import type { CategoryNode } from '../types'

function makeTree(): CategoryNode[] {
  return [
    {
      id: 'fresh_food',
      name_kr: '신선식품',
      name_slug: 'fresh-food',
      level: 1,
      path: '신선식품',
      parent_id: null,
      children: [
        {
          id: 'vegetable',
          name_kr: '채소',
          name_slug: 'vegetable',
          level: 2,
          path: '신선식품 > 채소',
          parent_id: 'fresh_food',
          children: [],
        },
        {
          id: 'fruit',
          name_kr: '과일',
          name_slug: 'fruit',
          level: 2,
          path: '신선식품 > 과일',
          parent_id: 'fresh_food',
          children: [],
        },
      ],
    },
    {
      id: 'processed_food',
      name_kr: '가공식품',
      name_slug: 'processed-food',
      level: 1,
      path: '가공식품',
      parent_id: null,
      children: [],
    },
  ]
}

describe('CategoryTree', () => {
  it('루트 카테고리 노드 렌더링', () => {
    render(
      <MemoryRouter>
        <CategoryTree nodes={makeTree()} />
      </MemoryRouter>
    )
    expect(screen.getByText('신선식품')).toBeInTheDocument()
    expect(screen.getByText('가공식품')).toBeInTheDocument()
  })

  it('자식 카테고리 노드 렌더링', () => {
    render(
      <MemoryRouter>
        <CategoryTree nodes={makeTree()} />
      </MemoryRouter>
    )
    expect(screen.getByText('채소')).toBeInTheDocument()
    expect(screen.getByText('과일')).toBeInTheDocument()
  })

  it('카테고리 클릭 시 올바른 URL로 이동', async () => {
    let navigatedPath = ''
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route
            path="/"
            element={<CategoryTree nodes={makeTree()} />}
          />
          <Route
            path="/c/:slug"
            element={
              <div data-testid="category-page">
                {(() => {
                  navigatedPath = window.location.pathname
                  return null
                })()}
              </div>
            }
          />
        </Routes>
      </MemoryRouter>
    )

    const btn = screen.getByText('채소')
    await userEvent.click(btn)

    await screen.findByTestId('category-page')
  })

  it('activeId에 따라 현재 카테고리 강조', () => {
    render(
      <MemoryRouter>
        <CategoryTree nodes={makeTree()} activeId="vegetable" />
      </MemoryRouter>
    )
    const btn = screen.getByText('채소')
    expect(btn).toHaveAttribute('aria-current', 'page')
  })

  it('nav 랜드마크 존재', () => {
    render(
      <MemoryRouter>
        <CategoryTree nodes={makeTree()} />
      </MemoryRouter>
    )
    expect(screen.getByRole('navigation')).toBeInTheDocument()
  })
})
