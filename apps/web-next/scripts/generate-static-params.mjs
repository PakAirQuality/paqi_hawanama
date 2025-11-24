import fs from 'fs/promises'
import path from 'path'

// Configuration - update with your API endpoints
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://hawanama-152782825429.asia-south1.run.app'

async function fetchCitySlugs() {
  try {
    console.log('Fetching city slugs from API...')
    const response = await fetch(`${API_BASE}/api/v1/cities`)
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    const data = await response.json()
    
    // Extract city slugs from the API response
    // The API returns cities in data.cities array
    const cities = data.cities || []
    const slugs = cities.map(city => city.slug).filter(Boolean)
    
    console.log(`Found ${slugs.length} city slugs`)
    return slugs
  } catch (error) {
    console.error('Error fetching city slugs:', error)
    throw error
  }
}

async function fetchStationIds() {
  try {
    console.log('Fetching station IDs from API...')
    const response = await fetch(`${API_BASE}/api/v1/dashboard/stations`)
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    const data = await response.json()
    
    // Extract hash-based station IDs from the API response
    // Backend now returns hash station_id as the primary ID field
    const stations = data.stations || []
    const ids = stations.map(station => station.id).filter(Boolean)
    
    console.log(`Found ${ids.length} station IDs (hash-based)`)
    return ids
  } catch (error) {
    console.error('Error fetching station IDs:', error)
    throw error
  }
}

async function generateStaticParams() {
  try {
    console.log('Starting static parameter generation...')
    
    // Create src/static directory if it doesn't exist
    const staticDir = path.join(process.cwd(), 'src', 'static')
    await fs.mkdir(staticDir, { recursive: true })
    
    // Fetch data from APIs
    const [citySlugs, stationIds] = await Promise.all([
      fetchCitySlugs(),
      fetchStationIds()
    ])
    
    // Write city slugs to JSON file
    const citySlugPath = path.join(staticDir, 'citySlugs.json')
    await fs.writeFile(citySlugPath, JSON.stringify(citySlugs, null, 2))
    console.log(`✅ Written ${citySlugs.length} city slugs to ${citySlugPath}`)
    
    // Write station IDs to JSON file
    const stationIdPath = path.join(staticDir, 'stationIds.json')
    await fs.writeFile(stationIdPath, JSON.stringify(stationIds, null, 2))
    console.log(`✅ Written ${stationIds.length} station IDs to ${stationIdPath}`)
    
    console.log('✅ Static parameter generation completed successfully!')
    
    // Log summary
    console.log('\n📊 Summary:')
    console.log(`- City pages to be generated: ${citySlugs.length}`)
    console.log(`- Station pages to be generated: ${stationIds.length}`)
    console.log(`- Total static pages: ${citySlugs.length + stationIds.length + 1}`) // +1 for homepage
    
  } catch (error) {
    console.error('❌ Error generating static parameters:', error)
    process.exit(1)
  }
}

// Run the script
generateStaticParams()