import { describe, expect, it } from 'vitest'
import type { CurrentStation } from '@/components/analyst-desk/types'
import { filterStationRows, groupStationRows, stationCities, stationRows, worstStation, type StationListItem, type StationRow } from './stationList'

const item = (id: string, name: string, place = 'Lahore, Punjab'): StationListItem => ({
  station_id: id, station_name: name, display_name: `${name}, ${place}, Pakistan`,
})

const live = (id: string, pm25: number | null, last_reading = '2026-11-02T10:00:00Z'): CurrentStation => ({
  id, name: id, latitude: 31.5, longitude: 74.3, city: 'Lahore', pm25, aqi_raw: null, aqi_category: '', last_reading,
})

const row = (name: string, pm25: number | null, city = 'Lahore'): StationRow => ({
  id: name, name, city, place: `${city}, Punjab`, displayName: `${name}, ${city}, Punjab, Pakistan`, pm25, lastReading: null,
})

describe('stationRows', () => {
  it('joins the directory to the latest readings by id', () => {
    expect(stationRows([item('a', 'GCU')], [live('a', 120)])[0]).toEqual({
      id: 'a', name: 'GCU', city: 'Lahore', place: 'Lahore, Punjab', displayName: 'GCU, Lahore, Punjab, Pakistan',
      pm25: 120, lastReading: '2026-11-02T10:00:00Z',
    })
  })

  it('keeps stations with no reading, marked as such', () => {
    const [r] = stationRows([item('a', 'GCU')], [])
    expect(r.pm25).toBeNull()
    expect(r.lastReading).toBeNull()
  })

  it('finds the city when the station name holds a comma', () => {
    expect(stationRows([item('a', 'BAM, Civil Secretariat', 'Quetta, Balochistan')], [])[0].city).toBe('Quetta')
  })

  it('falls back when the address has no city', () => {
    expect(stationRows([{ station_id: 'a', station_name: 'X', display_name: 'X, Pakistan' }], [])[0]).toMatchObject({ city: 'Other', place: '' })
  })
})

describe('filterStationRows', () => {
  const rows = [row('GCU', 120), row('Korangi', null, 'Karachi')]

  it('can leave out stations that are not reporting', () => {
    expect(filterStationRows(rows, '', true).map(r => r.name)).toEqual(['GCU'])
    expect(filterStationRows(rows, '', false)).toHaveLength(2)
  })

  it('searches names and cities, ignoring case and spaces', () => {
    expect(filterStationRows(rows, ' karachi ', false).map(r => r.name)).toEqual(['Korangi'])
    expect(filterStationRows(rows, 'gcu', false).map(r => r.name)).toEqual(['GCU'])
  })
})

describe('city filter', () => {
  const rows = [row('GCU', 120), row('Ravi Road', null), row('Korangi', 40, 'Karachi'), row('Sector F-7', null, 'Islamabad')]

  it('narrows to one city, and only an exact match', () => {
    expect(filterStationRows(rows, '', false, 'Lahore').map(r => r.name)).toEqual(['GCU', 'Ravi Road'])
    expect(filterStationRows(rows, '', false, 'Lah')).toEqual([])
  })

  it('combines with the other filters', () => {
    expect(filterStationRows(rows, '', true, 'Lahore').map(r => r.name)).toEqual(['GCU'])
    expect(filterStationRows(rows, 'ravi', false, 'Lahore').map(r => r.name)).toEqual(['Ravi Road'])
    expect(filterStationRows(rows, 'korangi', false, 'Lahore')).toEqual([])
  })

  it('lists cities A to Z with their station counts', () => {
    expect(stationCities(rows, false)).toEqual([
      { city: 'Islamabad', count: 1 }, { city: 'Karachi', count: 1 }, { city: 'Lahore', count: 2 },
    ])
  })

  it('counts only reporting stations when that is what is shown', () => {
    expect(stationCities(rows, true)).toEqual([{ city: 'Karachi', count: 1 }, { city: 'Lahore', count: 1 }])
  })
})

describe('groupStationRows', () => {
  const rows = [row('B', 90), row('A', 200), row('C', null), row('D', 50, 'Karachi')]

  it('puts the worst reading first and stations without one last', () => {
    expect(groupStationRows(rows, 'worst')).toEqual([{ city: null, rows: [rows[1], rows[0], rows[3], rows[2]] }])
  })

  it('groups by city in alphabetical order, worst first inside each', () => {
    const groups = groupStationRows(rows, 'city')
    expect(groups.map(g => g.city)).toEqual(['Karachi', 'Lahore'])
    expect(groups[1].rows.map(r => r.name)).toEqual(['A', 'B', 'C'])
  })

  it('leaves the rows it was given in their order', () => {
    groupStationRows(rows, 'worst')
    expect(rows.map(r => r.name)).toEqual(['B', 'A', 'C', 'D'])
  })

  it('returns nothing for an empty list', () => {
    expect(groupStationRows([], 'worst')).toEqual([])
    expect(groupStationRows([], 'city')).toEqual([])
  })
})

describe('worstStation', () => {
  it('finds the highest reading', () => {
    expect(worstStation([row('A', 90), row('B', 200), row('C', null)])?.name).toBe('B')
  })

  it('is null when nothing is reporting', () => {
    expect(worstStation([row('A', null)])).toBeNull()
  })
})
