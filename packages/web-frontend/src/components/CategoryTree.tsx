import { useNavigate } from 'react-router-dom'
import type { CategoryNode } from '../types'

interface CategoryTreeProps {
  nodes: CategoryNode[]
  activeId?: string
}

function CategoryNodeItem({
  node,
  activeId,
  navigate,
}: {
  node: CategoryNode
  activeId?: string
  navigate: (path: string) => void
}) {
  const isActive = node.id === activeId
  return (
    <li>
      <button
        data-category-id={node.id}
        onClick={() => navigate(`/c/${node.name_slug}`)}
        aria-current={isActive ? 'page' : undefined}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: `4px ${8 + (node.level - 1) * 12}px`,
          width: '100%',
          textAlign: 'left',
          fontSize: node.level === 1 ? '15px' : '13px',
          fontWeight: node.level === 1 ? 600 : 400,
          color: isActive ? '#2563eb' : '#374151',
          borderLeft: isActive ? '3px solid #2563eb' : '3px solid transparent',
        }}
      >
        {node.name_kr}
      </button>
      {node.children && node.children.length > 0 && (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {node.children.map((child) => (
            <CategoryNodeItem
              key={child.id}
              node={child}
              activeId={activeId}
              navigate={navigate}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

export function CategoryTree({ nodes, activeId }: CategoryTreeProps) {
  const navigate = useNavigate()
  return (
    <nav aria-label="카테고리 트리">
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {nodes.map((node) => (
          <CategoryNodeItem
            key={node.id}
            node={node}
            activeId={activeId}
            navigate={navigate}
          />
        ))}
      </ul>
    </nav>
  )
}
