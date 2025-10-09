'use client';
import {useEffect, useMemo, useRef} from 'react';
import type mapboxglType from 'mapbox-gl';
import {MapboxOverlay} from '@deck.gl/mapbox';
import {ColumnLayer} from '@deck.gl/layers';
import type { Station } from '@/lib/api';

// ---- helpers ----
const toRad = (d:number) => (d * Math.PI) / 180;
const haversineMeters = (lon1:number, lat1:number, lon2:number, lat2:number) => {
  const R = 6371008.8;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat/2)**2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
};

// meters per horizontal pixel at a given lng/lat (works on globe)
const metersPerPixelAt = (map: mapboxglType.Map, lon:number, lat:number) => {
  const p = map.project({lng: lon, lat});
  const p2 = {x: p.x + 1, y: p.y}; // +1 CSS px
  const ll1 = map.unproject(p);
  const ll2 = map.unproject(p2 as any);
  return haversineMeters(ll1.lng, ll1.lat, ll2.lng, ll2.lat);
};

const colorFor = (v:number):[number,number,number,number] =>
  v < 50 ? [64,196,255,220] :
  v < 100 ? [120,105,255,220] :
  v < 150 ? [255,140,0,230]  :
            [220,70,70,230];

const valueOf = (s: Station) => s.aqi_raw ?? s.pm25 ?? 0;

export function useDeckOverlay(map: mapboxglType.Map | null, stations: Station[]) {
  const overlayRef = useRef<MapboxOverlay | null>(null);

  const pillars = useMemo(() => {
    const ps: {position:[number,number], v:number, name?:string}[] = [];
    for (const s of stations) {
      if (s.longitude==null || s.latitude==null) continue;
      const v = valueOf(s);
      if (v <= 0) continue;
      ps.push({ position: [s.longitude, s.latitude], v, name: s.name });
    }
    return ps;
  }, [stations]);

  useEffect(() => {
    if (!map) return;

    if (!overlayRef.current) {
      overlayRef.current = new MapboxOverlay({ interleaved: false });
      map.addControl(overlayRef.current);
    }

    const buildLayers = () => {
      const z = map.getZoom();
      const pitch = map.getPitch();

      // Desired on-screen radius in pixels
      const targetPx = (v:number) => {
        const base =
          z <= 2 ? 260 :
          z <= 3 ? 200 :
          z <= 4 ? 140 :
          z <= 5 ? 100 :
          z <= 6 ? 70  : 44;
        const bump =
          (z <= 3 ? 0.6 : z <= 4 ? 0.4 : 0.25) * Math.min(v, 200);
        return base + bump;
      };

      const getRadiusMeters = (d:any) => {
        const [lon, lat] = d.position as [number, number];
        const mPerPx = metersPerPixelAt(map, lon, lat);
        const radiusMeters = targetPx(d.v) * mPerPx;
        console.log('m/px=', mPerPx, 'minPx=', minPx, 'radiusMeters=', radiusMeters);
        return radiusMeters; // meters so globe stays happy
      };

      const getElevationMeters = (d:any) => {
        const base =
          z <= 3 ? 300_000 :
          z <= 4 ? 160_000 :
          z <= 5 ? 80_000  : 40_000;
        const scale =
          z <= 3 ? 900 :
          z <= 4 ? 600 :
          z <= 5 ? 350 : 220;
        return base + d.v * scale;
      };

      // >>> KEY: clamp on-screen size no matter what the camera does
      const minPx =
        z <= 2 ? 240 :
        z <= 3 ? 190 :
        z <= 4 ? 140 :
        z <= 5 ? 100 :
        z <= 6 ? 70  : 44;

      const layer = new ColumnLayer({
        id: 'pillars',
        data: pillars,
        extruded: true,
        getPosition: (d:any) => d.position,

        getRadius: getRadiusMeters,          // meters
        radiusMinPixels: minPx,              // <-- guarantees fat columns
        radiusMaxPixels: 520,                // cap to avoid covering the map

        getElevation: getElevationMeters,    // meters
        getFillColor: (d:any) => colorFor(d.v),
        diskResolution: 24,
        coverage: 1,
        pickable: true,
        parameters: { depthTest: false },

        updateTriggers: {
          getRadius: [z, pitch, pillars.length],
          radiusMinPixels: [z],
          getElevation: [z],
          getFillColor: [pillars.length]
        }
      });

      overlayRef.current!.setProps({ layers: [layer] });
    };

    buildLayers();
    const onZoom  = () => buildLayers();
    const onPitch = () => buildLayers();
    const onMove  = () => buildLayers();
    map.on('zoom', onZoom);
    map.on('pitch', onPitch);
    map.on('move', onMove);

    return () => {
      map.off('zoom', onZoom);
      map.off('pitch', onPitch);
      map.off('move', onMove);
    };
  }, [map, pillars]);

  useEffect(() => {
    return () => {
      overlayRef.current?.finalize();
      overlayRef.current = null;
    };
  }, []);
}
