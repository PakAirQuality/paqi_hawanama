# Map Component Architecture

This directory contains a modular, well-organized map component system for the Hawanama air quality dashboard.

## 📁 Directory Structure

```
src/components/map/
├── README.md                     # This documentation
├── index.ts                      # Main exports
├── Map.tsx                       # Original monolithic component
├── MapRefactored.tsx            # New modular component
├── MapWrapper.tsx               # Dynamic loading wrapper
├── CityMap.tsx                  # City-specific map component
├── CityToggle.tsx               # Boundary toggle component
├── config/                      # Configuration files
│   ├── mapConfig.ts            # Map settings, styles, constants
│   ├── clusterConfig.ts        # Supercluster configuration
│   └── aqiStyles.ts            # AQI colors and styling logic
├── hooks/                       # Custom React hooks
│   ├── useStationsData.ts      # Station data fetching
│   ├── useSupercluster.ts      # Clustering logic
│   └── useMapInstance.ts       # Map initialization
├── services/                    # Business logic services
│   ├── MapSourceService.ts     # Data source management
│   ├── MapLayerService.ts      # Layer management
│   ├── MapEventService.ts      # Event handling
│   ├── FilterService.ts        # Station filtering logic
│   └── NavigationService.ts    # Route handling logic
└── utils/                       # Utility functions
    ├── mapUtils.ts             # Map helper functions
    ├── stationUtils.ts         # Station data transformations
    └── coordinateUtils.ts      # Geographic calculations
```

## 🎯 Key Benefits

### **Single Responsibility**
- Each file handles one specific concern
- Clear separation between data, business logic, and presentation

### **Testability** 
- Services and utilities can be unit tested independently
- Hooks can be tested in isolation
- Mock dependencies easily

### **Reusability**
- Hooks and services can be used by other components
- Configuration can be shared across map instances
- Utilities are pure functions

### **Type Safety**
- Strong TypeScript interfaces between modules
- Clear contracts for service interactions
- Configuration objects are properly typed

### **Maintainability**
- Easy to locate and modify specific functionality
- Adding new features doesn't require touching multiple concerns
- Clear dependency relationships

## 🔧 Usage Examples

### Using the Refactored Component
```tsx
import { MapRefactored } from '@/components/map'

function App() {
  return (
    <MapRefactored 
      center={[69.35, 30.38]}
      zoom={5}
      cityBoundariesVisible={true}
      className="w-full h-screen"
    />
  )
}
```

### Using Individual Services
```tsx
import { FilterService, NavigationService } from '@/components/map'

// Filter stations by zoom level
const visibleStations = FilterService.filterByZoom(stations, 8)

// Navigate to city page
NavigationService.navigateToCity("Karachi")
```

### Using Hooks Independently
```tsx
import { useStationsData, useSupercluster } from '@/components/map'

function CustomMapComponent() {
  const { stations, loading, error } = useStationsData()
  const supercluster = useSupercluster(stations)
  
  // Custom component logic
}
```

### Using Configuration
```tsx
import { AQI_COLORS, getAQICategory } from '@/components/map'

const color = AQI_COLORS[getAQICategory(150)] // Returns orange for unhealthy_sensitive
```

## 🛠 Migration Guide

### From Original Map.tsx
The original `Map.tsx` is preserved for backward compatibility. To migrate:

1. **Replace import**: Change `import Map from './Map'` to `import { MapRefactored as Map } from './Map'`
2. **Update MapWrapper**: Set `useRefactored={true}` in MapWrapper props
3. **Test functionality**: Verify all features work as expected

### Testing Both Versions
```tsx
// Test refactored version
<MapWrapper useRefactored={true} cityBoundariesVisible={true} />

// Test original version  
<MapWrapper useRefactored={false} cityBoundariesVisible={true} />
```

## 📋 Service Documentation

### FilterService
- `filterByZoom()` - Hide grey stations at low zoom
- `filterByBounds()` - Geographic filtering
- `filterByCity()` - City-specific filtering
- `filterByQuality()` - Data quality filtering
- `applyFilters()` - Chain multiple filters

### NavigationService
- `navigateToCity()` - Navigate to city page
- `navigateToStation()` - Navigate to station page
- `createCitySlug()` - URL-friendly city names
- `handleBoundaryClick()` - Smart boundary navigation

### MapSourceService
- `initializeSources()` - Setup map data sources
- `updateClusters()` - Update cluster data
- `updatePoints()` - Update station points
- `updateCityBoundaries()` - Manage boundary data

## 🧪 Testing Strategy

### Unit Tests
```typescript
// Test individual services
describe('FilterService', () => {
  it('should filter stations by zoom level', () => {
    const result = FilterService.filterByZoom(mockStations, 5)
    expect(result).toHaveLength(expectedCount)
  })
})
```

### Integration Tests
```typescript
// Test hook combinations
describe('Map Integration', () => {
  it('should cluster stations correctly', () => {
    const { result } = renderHook(() => {
      const { stations } = useStationsData()
      return useSupercluster(stations)
    })
    expect(result.current).toBeDefined()
  })
})
```

## 🔄 Future Enhancements

1. **Layer Plugins**: Extensible layer system for custom visualizations
2. **Theme System**: Dynamic color schemes and styling
3. **Performance Monitoring**: Built-in metrics and optimization
4. **Accessibility**: Screen reader support and keyboard navigation
5. **Mobile Optimization**: Touch gestures and responsive design

## 📊 Performance Considerations

- **Lazy Loading**: Services are only instantiated when needed
- **Memoization**: Heavy computations are cached appropriately  
- **Tree Shaking**: Unused utilities are excluded from bundle
- **Code Splitting**: Mapbox GL is dynamically imported
- **Service Cleanup**: Proper resource disposal prevents memory leaks

---

*This modular architecture significantly improves code maintainability while preserving all existing functionality.*