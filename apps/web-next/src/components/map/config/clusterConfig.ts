export const CLUSTER_CONFIG = {
  radius: 40,     // Small radius - only cluster when stations overlap
  maxZoom: 18,    // Cluster until very high zoom, then show all individual stations
  minZoom: 0,     // Start clustering from the lowest zoom
  minPoints: 5,   // Need at least 5 stations to form a cluster (only dense areas)
};

export const CLUSTER_BEHAVIOR = {
  lockZoom: 10,
};