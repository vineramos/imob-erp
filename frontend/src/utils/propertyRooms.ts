export function formatBedroomSummary(bedrooms: number, suites: number) {
  const roomLabel = bedrooms === 1 ? 'quarto' : 'quartos'
  if (suites <= 0) return `${bedrooms} ${roomLabel}`
  const suiteLabel = suites === 1 ? 'suíte' : 'suítes'
  return `${bedrooms} ${roomLabel} (${suites} ${suiteLabel})`
}
