import { useMemo } from 'react';
import Supercluster from 'supercluster';
import type { Station } from '@/lib/api';
import { CLUSTER_CONFIG } from '../config/clusterConfig';
import { stationsToGeoJSONPoints } from '../utils/stationUtils';

export const useSupercluster = (stations: Station[]) => {
  const points = useMemo(() => stationsToGeoJSONPoints(stations), [stations]);

  const supercluster = useMemo(() => {
    if (!points.length) return null;

    const sc = new Supercluster({
      ...CLUSTER_CONFIG,
      // This function runs for each individual point
      map: (props) => ({
        id: props.id,
        aqi: props.aqi_raw, // Keep AQI for color calculation
        pm25: props.pm25, // Use PM2.5 from Station interface
        pm25_sum: props.pm25 ?? null, // Preserve null PM2.5 values
        total_points: 1,
        valid_readings: props.pm25 !== null && props.pm25 !== undefined ? 1 : 0,
      }),
      // This function combines two clusters or a point and a cluster
      reduce: (acc, props) => {
        // Only add non-null PM2.5 values to the sum
        if (props.pm25_sum !== null) {
          acc.pm25_sum = (acc.pm25_sum ?? 0) + props.pm25_sum;
        }
        acc.total_points += props.total_points;
        acc.valid_readings += props.valid_readings;
        // Calculate average PM2.5 for clusters
        if (acc.valid_readings > 0) {
          acc.avg_pm25 = (acc.pm25_sum ?? 0) / acc.valid_readings;
        }
      },
    });

    sc.load(points);
    console.log("Supercluster instance created and loaded with points.");
    return sc;
  }, [points]);

  return supercluster;
};