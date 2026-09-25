export function shiftMonth(value: string, direction: number) {
  const [year, month] = value.split('-').map(Number)
  const base = Number.isFinite(year) && Number.isFinite(month)
    ? new Date(year, month - 1, 1)
    : new Date()
  base.setDate(1)
  base.setMonth(base.getMonth() + direction)
  return `${base.getFullYear()}-${String(base.getMonth() + 1).padStart(2, '0')}`
}
