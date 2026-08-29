import { StationProfileClient } from "./StationProfileClient"
import stationIds from "@/data/station-ids.json"

export function generateStaticParams() {
  return (stationIds as string[]).map((id) => ({ stationId: id }))
}

export default function StationProfilePage() {
  return <StationProfileClient />
}
