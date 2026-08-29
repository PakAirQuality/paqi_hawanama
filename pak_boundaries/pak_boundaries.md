# Pakistan Administrative Boundaries

All boundaries in this project are sourced from **geoBoundaries** — a global open database of political administrative boundaries maintained by the William & Mary geoLab.

## Source

- **Provider**: geoBoundaries (www.geoboundaries.org)
- **Country**: Pakistan (PAK)
- **License**: CC BY 4.0 (Attribution required)
- **Boundary Year**: 2019
- **Build Date**: Dec 12, 2023

## Files

| Level | Folder | Description | Features |
|-------|--------|-------------|----------|
| ADM0 | `geoBoundaries-PAK-ADM0-all/` | Country boundary | 1 |
| ADM1 | `geoBoundaries-PAK-ADM1-all/` | Provinces (Balochistan, Punjab, Sindh, KP, ICT, GB, AJK) | 7 |
| ADM2 | `geoBoundaries-PAK-ADM2-all/` | Districts | 126 |
| ADM3 | `geoBoundaries-PAK-ADM3-all/` | Tehsils / sub-districts | ~500+ |

Each folder contains the full geoBoundaries release: GeoJSON, Shapefile, TopoJSON, simplified variants, metadata, and citation.

## Property Schema

All GeoJSON features share a consistent schema:

- `shapeName` — Name of the administrative unit
- `shapeISO` — ISO code (where available)
- `shapeID` — Unique geoBoundaries ID
- `shapeGroup` — Country group (PAK)
- `shapeType` — Boundary level (ADM0/ADM1/ADM2/ADM3)

## Where These Are Used

These canonical files are copied to:

- `apps/dashboard-frontend/public/` — Frontend map rendering (Mapbox GL JS)
- `apps/web-next/public/` — Public AQI dashboard maps
- `apps/api/data/` — Server-side tile clipping and spatial queries
- `deployment/data/` (Estimation repo) — Inference pipeline masking

**All copies must come from this folder.** Do not source boundaries from Mapbox, Natural Earth, or other providers.

## Citation

> Runfola D, Anderson A, Baier H, Crittenden M, Dowker E, Fuhrig S, et al. (2020)
> geoBoundaries: A global database of political administrative boundaries.
> PLoS ONE 15(4): e0231866. https://doi.org/10.1371/journal.pone.0231866
