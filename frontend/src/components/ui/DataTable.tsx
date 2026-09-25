import type { ReactNode } from 'react'
import { EmptyState } from './EmptyState'

export type DataTableColumn<Row> = {
  key: string
  header: ReactNode
  cell: (row: Row) => ReactNode
  width?: string
  align?: 'left' | 'center' | 'right'
}

type DataTableProps<Row> = {
  columns: readonly DataTableColumn<Row>[]
  rows: readonly Row[]
  rowKey: (row: Row) => string
  ariaLabel: string
  loading?: boolean
  emptyTitle?: string
  emptyDescription?: string
  onRowClick?: (row: Row) => void
}

export function DataTable<Row>({ columns, rows, rowKey, ariaLabel, loading = false, emptyTitle = 'Nenhum registro encontrado', emptyDescription, onRowClick }: DataTableProps<Row>) {
  if (loading) return <div className="ui-table-state" role="status">Carregando dados...</div>
  if (!rows.length) return <EmptyState title={emptyTitle} description={emptyDescription} compact />
  return <div className="ui-table-wrap"><table className="ui-data-table" aria-label={ariaLabel}>
    <thead><tr>{columns.map(column => <th key={column.key} style={{ width: column.width, textAlign: column.align }}>{column.header}</th>)}</tr></thead>
    <tbody>{rows.map(row => <tr
      key={rowKey(row)}
      className={onRowClick ? 'is-interactive' : undefined}
      tabIndex={onRowClick ? 0 : undefined}
      onClick={() => onRowClick?.(row)}
      onKeyDown={event => {
        if (onRowClick && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault()
          onRowClick(row)
        }
      }}
    >{columns.map(column => <td key={column.key} style={{ textAlign: column.align }}>{column.cell(row)}</td>)}</tr>)}</tbody>
  </table></div>
}
