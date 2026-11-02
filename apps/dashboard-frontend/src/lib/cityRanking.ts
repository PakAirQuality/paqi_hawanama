// Which cities may appear in a "worst cities" list. A city mean from one or two monitors can be
// one bad sensor, so only cities with more than 5 monitors reporting that day are ranked.

export const MIN_CITY_MONITORS = 6
const MAX_RANKED_CITIES = 5

/** Expects cities sorted worst first; `count` is the monitors reporting that day. */
export function worstRankedCities<T extends { count: number }>(cities: T[]): T[] {
  return cities.filter(c => c.count >= MIN_CITY_MONITORS).slice(0, MAX_RANKED_CITIES)
}
