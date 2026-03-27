"""Canned tool return values for all 9 copilot tools.

Keys are referenced by `mock_output_key` in core_cases.json / regression_cases.json.
"""

MOCK_OUTPUTS: dict[str, dict] = {
    # ── aq_hotspots_daily ────────────────────────────────────────────
    "hotspots_pakistan_top5": {
        "date": "2026-03-06",
        "data": {
            "geography": "city",
            "metric": "avg_pm25",
            "hotspots": [
                {"name": "Lahore", "avg_pm25": 213.5, "max_pm25": 298.0, "station_count": 12, "risk_band": "very_unhealthy"},
                {"name": "Faisalabad", "avg_pm25": 178.2, "max_pm25": 221.0, "station_count": 5, "risk_band": "very_unhealthy"},
                {"name": "Karachi", "avg_pm25": 142.7, "max_pm25": 189.3, "station_count": 8, "risk_band": "unhealthy"},
                {"name": "Peshawar", "avg_pm25": 118.9, "max_pm25": 156.0, "station_count": 4, "risk_band": "unhealthy"},
                {"name": "Islamabad", "avg_pm25": 89.4, "max_pm25": 112.0, "station_count": 6, "risk_band": "unhealthy"},
            ],
        },
        "basis": {
            "description": "24h station observations",
            "sources": ["station_observations"],
            "coverage_scope": "last_24h",
        },
        "action_hint": "",
        "followups": ["Tell me about Lahore", "Compare with yesterday", "What's driving pollution?"],
    },
    "hotspots_pakistan_top3": {
        "date": "2026-03-06",
        "data": {
            "geography": "city",
            "metric": "avg_pm25",
            "hotspots": [
                {"name": "Lahore", "avg_pm25": 213.5, "max_pm25": 298.0, "station_count": 12, "risk_band": "very_unhealthy"},
                {"name": "Faisalabad", "avg_pm25": 178.2, "max_pm25": 221.0, "station_count": 5, "risk_band": "very_unhealthy"},
                {"name": "Karachi", "avg_pm25": 142.7, "max_pm25": 189.3, "station_count": 8, "risk_band": "unhealthy"},
            ],
        },
        "basis": {
            "description": "24h station observations",
            "sources": ["station_observations"],
            "coverage_scope": "last_24h",
        },
        "action_hint": "",
        "followups": ["Tell me about Lahore", "Compare with yesterday"],
    },

    # ── aq_city_detail ───────────────────────────────────────────────
    "city_detail_lahore": {
        "date": "2026-03-06",
        "data": {
            "city": "Lahore",
            "avg_pm25": 213.5,
            "max_pm25": 298.0,
            "station_count": 12,
            "risk_band": "very_unhealthy",
            "trend_24h": "+18.3",
            "stations": [
                {"station_name": "US Consulate Lahore", "pm25": 298.0, "risk_band": "severe"},
                {"station_name": "Lahore - Mall Road", "pm25": 234.1, "risk_band": "very_unhealthy"},
                {"station_name": "Lahore - Township", "pm25": 189.7, "risk_band": "very_unhealthy"},
            ],
        },
        "basis": {
            "description": "Current station observations for Lahore",
            "sources": ["station_observations"],
            "coverage_scope": "last_24h",
        },
        "action_hint": '{{ACTION:{"type":"zoom_to_city","city":"Lahore"}}}',
        "followups": ["Why is Lahore so bad?", "Compare with yesterday", "Show forecast"],
    },

    # ── aq_compare_dates ─────────────────────────────────────────────
    "compare_yesterday_national": {
        "date": "2026-03-06",
        "data": {
            "date1": "2026-03-05",
            "date2": "2026-03-06",
            "direction": "worsened",
            "delta_mean_pm25": 22.4,
            "biggest_movers": [
                {"city": "Lahore", "delta": 45.1, "direction": "worsened"},
                {"city": "Faisalabad", "delta": 31.2, "direction": "worsened"},
                {"city": "Islamabad", "delta": -12.8, "direction": "improved"},
            ],
            "driver_explanation": {
                "primary": "stagnation",
                "stagnation_score_change": "34→72",
                "transport_score_change": "18→12",
            },
        },
        "basis": {
            "description": "Comparison of 24h station observations",
            "sources": ["station_observations"],
            "coverage_scope": "last_48h",
        },
        "action_hint": "",
        "followups": ["Why did Lahore worsen?", "Show Islamabad detail"],
    },

    # ── aq_explain_drivers ───────────────────────────────────────────
    "drivers_lahore": {
        "date": "2026-03-06",
        "data": {
            "target": "Lahore",
            "drivers": [
                {
                    "driver": "stagnation",
                    "score": 72,
                    "evidence": [
                        "Low wind speed (1.2 m/s avg)",
                        "Shallow boundary layer (320m)",
                        "Temperature inversion detected",
                    ],
                },
                {
                    "driver": "local_emissions",
                    "score": 45,
                    "evidence": [
                        "Morning traffic peak correlation",
                        "Industrial zone contribution",
                    ],
                },
                {
                    "driver": "fire_activity",
                    "score": 18,
                    "evidence": [
                        "3 FIRMS hotspots within 50km (low)",
                    ],
                },
            ],
            "limitations": ["Boundary layer height estimated from model, not observed"],
        },
        "basis": {
            "description": "Driver attribution from forecast watchlist + current observations",
            "sources": ["watchlist", "station_observations"],
            "driver_source": "forecast_estimation",
        },
        "action_hint": "",
        "followups": ["Show Lahore stations", "Compare with yesterday"],
    },

    # ── aq_incident_summary ──────────────────────────────────────────
    "incidents_pakistan": {
        "date": "2026-03-06",
        "data": {
            "total_incidents": 8,
            "incidents": [
                {"city": "Lahore", "type": "severe_ramp", "severity": "critical", "pm25": 298.0, "station_name": "US Consulate Lahore"},
                {"city": "Lahore", "type": "persistent_high", "severity": "critical", "pm25": 234.1, "station_name": "Lahore - Mall Road"},
                {"city": "Faisalabad", "type": "ramp_likely", "severity": "warning", "pm25": 221.0, "station_name": "Faisalabad - City Center"},
                {"city": "Karachi", "type": "rising", "severity": "warning", "pm25": 189.3, "station_name": "Karachi - Clifton"},
            ],
        },
        "basis": {
            "description": "Watchlist alerts enriched with current observations",
            "sources": ["watchlist", "station_observations"],
        },
        "action_hint": "",
        "followups": ["Tell me about the Lahore ramp", "Show Faisalabad detail"],
    },

    # ── aq_forecast_audit ────────────────────────────────────────────
    "audit_single_day": {
        "date": "2026-03-06",
        "data": {
            "period": "2026-03-06",
            "n_days": 1,
            "metrics": {
                "mae": 18.4,
                "rmse": 27.1,
                "bias": 3.2,
                "r_squared": 0.82,
                "f1_at_150": 0.76,
            },
            "prediction_stats": {
                "total_stations": 510,
                "verified_stations": 423,
            },
            "alerts": ["Bias slightly positive — model over-predicting by 3.2 µg/m³"],
        },
        "basis": {
            "description": "Forecast vs observation verification",
            "sources": ["forecast", "station_observations"],
        },
        "action_hint": "",
        "followups": ["Show 7-day trend", "Which stations had worst errors?"],
    },

    # ── aq_station_focus ─────────────────────────────────────────────
    "station_focus_us_consulate": {
        "date": "2026-03-06",
        "data": {
            "station_name": "US Consulate Lahore",
            "city": "Lahore",
            "station_id": "a1b2c3d4e5f60001",
            "current_pm25": 298.0,
            "forecast": {
                "D+1": {"pm25_forecast": 275.0, "pm25_q90": 320.0, "risk_band": "severe", "ramp_detected": True},
                "D+2": {"pm25_forecast": 245.0, "pm25_q90": 290.0, "risk_band": "very_unhealthy", "ramp_detected": False},
                "D+3": {"pm25_forecast": 198.0, "pm25_q90": 240.0, "risk_band": "very_unhealthy", "ramp_detected": False},
            },
            "risk_band": "severe",
            "episode_state": "severe_ramp_likely",
            "confidence": "high",
            "priority": "escalate",
        },
        "action_hint": '{{ACTION:{"type":"zoom_to_station","station_id":"a1b2c3d4e5f60001","lat":31.56,"lng":74.35}}}',
        "followups": ["Show 24h trend", "Compare with neighbors", "Why is it elevated?"],
    },

    # ── aq_station_history ───────────────────────────────────────────
    "station_history_us_consulate_24h": {
        "date": "2026-03-06",
        "data": {
            "history": {
                "station_name": "US Consulate Lahore",
                "station_id": "a1b2c3d4e5f60001",
                "hours": 24,
                "readings": [
                    {"timestamp": "2026-03-05T12:00:00", "pm25": 185.0},
                    {"timestamp": "2026-03-05T18:00:00", "pm25": 220.0},
                    {"timestamp": "2026-03-06T00:00:00", "pm25": 260.0},
                    {"timestamp": "2026-03-06T06:00:00", "pm25": 285.0},
                    {"timestamp": "2026-03-06T12:00:00", "pm25": 298.0},
                ],
                "avg_pm25": 249.6,
                "trend": "rising",
            },
            "neighbours": [
                {"station_name": "Lahore - Mall Road", "pm25": 234.1, "distance_km": 3.2},
                {"station_name": "Lahore - Township", "pm25": 189.7, "distance_km": 7.1},
            ],
        },
        "action_hint": '{{ACTION:{"type":"show_station_trend","station_id":"a1b2c3d4e5f60001","station_name":"US Consulate Lahore","hours":24}}}',
        "followups": ["Tell me about Lahore - Mall Road", "Why is it elevated?", "What's the forecast?"],
    },

    # ── aq_data_coverage ─────────────────────────────────────────────
    "coverage_lahore_summary": {
        "date": "2026-03-06",
        "data": {
            "entity": "Lahore",
            "geography": "city",
            "detail_level": "summary",
            "total_stations": 12,
            "earliest_reading": "2019-01-15T08:00:00",
            "latest_reading": "2026-03-06T11:00:00",
            "total_readings": 1_250_000,
            "coverage_days": 2607,
            "oldest_station_preview": [
                {"station_name": "US Consulate Lahore", "earliest": "2019-01-15T08:00:00"},
                {"station_name": "Lahore - Mall Road", "earliest": "2020-03-01T00:00:00"},
                {"station_name": "Lahore - Township", "earliest": "2021-06-12T10:00:00"},
            ],
        },
        "basis": {
            "description": "Coverage derived from raw observations table",
            "sources": ["station_observations"],
            "coverage_scope": "full_history",
            "history_limit_applied": False,
        },
        "followups": ["Show full station breakdown for Lahore", "Show historical trend for Lahore"],
    },
    "coverage_national_summary": {
        "date": "2026-03-06",
        "data": {
            "entity": "Pakistan",
            "geography": "national",
            "detail_level": "summary",
            "total_stations": 510,
            "earliest_reading": "2017-11-20T00:00:00",
            "latest_reading": "2026-03-06T11:00:00",
            "total_readings": 45_000_000,
            "coverage_days": 3029,
            "oldest_station_preview": [
                {"station_name": "US Embassy Islamabad", "earliest": "2017-11-20T00:00:00"},
                {"station_name": "US Consulate Lahore", "earliest": "2019-01-15T08:00:00"},
                {"station_name": "US Consulate Karachi", "earliest": "2019-02-01T00:00:00"},
            ],
        },
        "basis": {
            "description": "Coverage derived from raw observations table",
            "sources": ["station_observations"],
            "coverage_scope": "full_history",
            "history_limit_applied": False,
        },
        "followups": ["Show full station breakdown", "Which cities have the longest history?"],
    },

    # ── Fire-dominant drivers ──────────────────────────────────────────
    "drivers_lahore_fire_dominant": {
        "date": "2026-03-06",
        "data": {
            "target": "Lahore",
            "drivers": [
                {
                    "driver": "fire_activity",
                    "score": 72,
                    "evidence": [
                        "42 FIRMS hotspots within 50km",
                        "Thermal anomaly cluster detected NW of city",
                    ],
                },
                {
                    "driver": "stagnation",
                    "score": 35,
                    "evidence": [
                        "Moderate wind speed (2.1 m/s avg)",
                    ],
                },
            ],
            "limitations": ["FIRMS detects thermal anomalies only — fire type cannot be determined"],
        },
        "basis": {
            "description": "Driver attribution from FIRMS NRT + watchlist",
            "sources": ["watchlist", "station_observations", "firms_nrt"],
            "driver_source": "scored",
        },
        "action_hint": "",
        "followups": ["Show fire hotspot map", "Which stations are closest?"],
    },
    "drivers_peshawar_no_fire": {
        "date": "2026-03-06",
        "data": {
            "target": "Peshawar",
            "drivers": [
                {
                    "driver": "stagnation",
                    "score": 65,
                    "evidence": [
                        "Low wind speed (1.5 m/s avg)",
                        "Shallow boundary layer (280m)",
                    ],
                },
                {
                    "driver": "fire_activity",
                    "score": 5,
                    "evidence": [
                        "No significant FIRMS hotspots within 100km",
                    ],
                },
            ],
        },
        "basis": {
            "description": "Driver attribution from watchlist",
            "sources": ["watchlist", "station_observations"],
            "driver_source": "scored",
        },
        "action_hint": "",
        "followups": ["Show Peshawar stations", "Compare with yesterday"],
    },
    "drivers_lahore_estimated": {
        "date": "2026-03-06",
        "data": {
            "target": "Lahore",
            "estimated": True,
            "drivers": [
                {
                    "driver": "stagnation",
                    "score": 60,
                    "evidence": [
                        "Low wind speed (estimated from model)",
                    ],
                },
                {
                    "driver": "fire_activity",
                    "score": 30,
                    "evidence": [
                        "FIRMS data unavailable — estimated from seasonal baseline",
                    ],
                },
            ],
            "limitations": [
                "Driver scores are estimated from model outputs, not from direct measurements",
                "FIRMS NRT data was unavailable at analysis time",
            ],
        },
        "basis": {
            "description": "Estimated driver attribution (FIRMS unavailable)",
            "sources": ["watchlist"],
            "driver_source": "forecast_estimation",
        },
        "action_hint": "",
        "followups": ["Show Lahore stations", "When will FIRMS data be available?"],
    },
    "drivers_lahore_trajectory": {
        "date": "2026-03-06",
        "data": {
            "target": "Lahore",
            "drivers": [
                {
                    "driver": "fire_activity",
                    "score": 68,
                    "evidence": [
                        "28 FIRMS hotspots within 75km",
                        "Trajectory-fire intersection detected",
                    ],
                },
                {
                    "driver": "transport",
                    "score": 55,
                    "evidence": [
                        "HYSPLIT back-trajectory indicates northwest transport corridor",
                    ],
                },
            ],
            "trajectory": {
                "upwind_direction": "northwest",
                "fire_intersections": 3,
                "transport_time_hours": 8,
                "source_region": "Indian Punjab agricultural belt",
            },
            "limitations": ["Trajectory model resolution is 0.5 degrees — local effects may differ"],
        },
        "basis": {
            "description": "Driver attribution with HYSPLIT trajectory analysis",
            "sources": ["watchlist", "station_observations", "firms_nrt", "hysplit"],
        },
        "action_hint": "",
        "followups": ["Show trajectory map", "Which other cities are in the corridor?"],
    },

    # ── NRT fire provenance ────────────────────────────────────────────
    "drivers_lahore_with_nrt_fire": {
        "date": "2026-03-06",
        "data": {
            "target": "Lahore",
            "drivers": [
                {
                    "driver": "fire_activity",
                    "score": 58,
                    "evidence": [
                        "15 FIRMS NRT hotspots within 50km",
                        "NRT fire detection from MODIS/VIIRS",
                    ],
                    "data_source": "firms_nrt",
                },
                {
                    "driver": "stagnation",
                    "score": 50,
                    "evidence": [
                        "Low wind speed (1.8 m/s avg)",
                    ],
                },
            ],
        },
        "basis": {
            "description": "Driver attribution including near-real-time fire data",
            "sources": ["watchlist", "station_observations", "firms_nrt"],
            "driver_source": "scored",
        },
        "action_hint": "",
        "followups": ["Show fire hotspot map", "Show Lahore stations"],
    },

    # ── Comparison with driver explanation ─────────────────────────────
    "compare_yesterday_with_drivers": {
        "date": "2026-03-06",
        "data": {
            "date1": "2026-03-05",
            "date2": "2026-03-06",
            "direction": "worsened",
            "delta_mean_pm25": 28.7,
            "biggest_movers": [
                {"city": "Lahore", "delta": 52.3, "direction": "worsened"},
                {"city": "Faisalabad", "delta": 18.5, "direction": "worsened"},
                {"city": "Islamabad", "delta": -8.2, "direction": "improved"},
            ],
            "driver_explanation": {
                "primary": "fire_activity",
                "fire_score_change": "22 to 58",
                "stagnation_score_change": "40 to 50",
                "transport_score_change": "15 to 32",
            },
        },
        "basis": {
            "description": "Comparison of 24h station observations with driver summary",
            "sources": ["station_observations", "driver_summary"],
            "coverage_scope": "last_48h",
        },
        "action_hint": "",
        "followups": ["Why did fire increase?", "Show Lahore detail"],
    },

    # ── Station focus: with forecast provenance ────────────────────────
    "station_focus_with_forecast": {
        "date": "2026-03-06",
        "data": {
            "station_name": "Lahore - Mall Road",
            "city": "Lahore",
            "station_id": "a1b2c3d4e5f60002",
            "current_pm25": 234.1,
            "current_source": "observation",
            "forecast": {
                "D+1": {"pm25_forecast": 220.0, "pm25_q90": 265.0, "risk_band": "very_unhealthy", "ramp_detected": False},
                "D+2": {"pm25_forecast": 195.0, "pm25_q90": 238.0, "risk_band": "very_unhealthy", "ramp_detected": False},
                "D+3": {"pm25_forecast": 170.0, "pm25_q90": 210.0, "risk_band": "unhealthy", "ramp_detected": False},
            },
            "risk_band": "very_unhealthy",
            "episode_state": "persistent_high",
            "confidence": "medium",
            "priority": "review",
        },
        "action_hint": '{{ACTION:{"type":"zoom_to_station","station_id":"a1b2c3d4e5f60002","lat":31.55,"lng":74.34}}}',
        "followups": ["Show 24h trend", "Compare with neighbors", "Why is it elevated?"],
    },

    # ── Station focus: not found ───────────────────────────────────────
    "station_focus_not_found": {
        "date": "2026-03-06",
        "data": {
            "error": "not_found",
            "query": "Imaginary Station XYZ",
            "message": "No station matching 'Imaginary Station XYZ' found in the network",
            "suggestion": "Try searching by city name or check the station list",
        },
        "basis": {
            "description": "Station lookup failed",
            "sources": [],
        },
        "action_hint": "",
        "followups": ["Show all stations in Lahore", "What cities are available?"],
    },

    # ── Faisalabad mocks (workflow cases) ──────────────────────────────
    "drivers_faisalabad": {
        "date": "2026-03-06",
        "data": {
            "target": "Faisalabad",
            "drivers": [
                {
                    "driver": "stagnation",
                    "score": 68,
                    "evidence": [
                        "Low wind speed (1.0 m/s avg)",
                        "Temperature inversion detected",
                    ],
                },
                {
                    "driver": "local_emissions",
                    "score": 52,
                    "evidence": [
                        "Industrial zone peak emissions",
                        "Rush hour traffic correlation",
                    ],
                },
            ],
        },
        "basis": {
            "description": "Driver attribution from watchlist",
            "sources": ["watchlist", "station_observations"],
            "driver_source": "scored",
        },
        "action_hint": "",
        "followups": ["Show Faisalabad stations", "Compare with yesterday"],
    },
    "station_focus_faisalabad": {
        "date": "2026-03-06",
        "data": {
            "station_name": "Faisalabad - City Center",
            "city": "Faisalabad",
            "station_id": "b2c3d4e5f6a70003",
            "current_pm25": 221.0,
            "forecast": {
                "D+1": {"pm25_forecast": 210.0, "pm25_q90": 255.0, "risk_band": "very_unhealthy", "ramp_detected": False},
                "D+2": {"pm25_forecast": 188.0, "pm25_q90": 230.0, "risk_band": "very_unhealthy", "ramp_detected": False},
                "D+3": {"pm25_forecast": 165.0, "pm25_q90": 200.0, "risk_band": "unhealthy", "ramp_detected": False},
            },
            "risk_band": "very_unhealthy",
            "episode_state": "ramp_likely",
            "confidence": "medium",
            "priority": "review",
        },
        "action_hint": '{{ACTION:{"type":"zoom_to_station","station_id":"b2c3d4e5f6a70003","lat":31.42,"lng":73.08}}}',
        "followups": ["Show 24h trend", "Why is it elevated?"],
    },
    "station_history_faisalabad_24h": {
        "date": "2026-03-06",
        "data": {
            "history": {
                "station_name": "Faisalabad - City Center",
                "station_id": "b2c3d4e5f6a70003",
                "hours": 24,
                "readings": [
                    {"timestamp": "2026-03-05T12:00:00", "pm25": 165.0},
                    {"timestamp": "2026-03-05T18:00:00", "pm25": 190.0},
                    {"timestamp": "2026-03-06T00:00:00", "pm25": 210.0},
                    {"timestamp": "2026-03-06T06:00:00", "pm25": 218.0},
                    {"timestamp": "2026-03-06T12:00:00", "pm25": 221.0},
                ],
                "avg_pm25": 200.8,
                "trend": "rising",
            },
            "neighbours": [
                {"station_name": "Faisalabad - Jhang Road", "pm25": 195.2, "distance_km": 4.5},
            ],
        },
        "action_hint": '{{ACTION:{"type":"show_station_trend","station_id":"b2c3d4e5f6a70003","station_name":"Faisalabad - City Center","hours":24}}}',
        "followups": ["Why is it elevated?", "Show forecast"],
    },

    # ── Karachi mocks (workflow context-switch) ────────────────────────
    "city_detail_karachi": {
        "date": "2026-03-06",
        "data": {
            "city": "Karachi",
            "avg_pm25": 142.7,
            "max_pm25": 189.3,
            "station_count": 8,
            "risk_band": "unhealthy",
            "trend_24h": "+12.1",
            "stations": [
                {"station_name": "Karachi - Clifton", "pm25": 189.3, "risk_band": "very_unhealthy"},
                {"station_name": "Karachi - DHA", "pm25": 155.0, "risk_band": "unhealthy"},
                {"station_name": "Karachi - North Nazimabad", "pm25": 130.5, "risk_band": "unhealthy"},
            ],
        },
        "basis": {
            "description": "Current station observations for Karachi",
            "sources": ["station_observations"],
            "coverage_scope": "last_24h",
        },
        "action_hint": '{{ACTION:{"type":"zoom_to_city","city":"Karachi"}}}',
        "followups": ["Why is Karachi worsening?", "Compare with yesterday", "Show forecast"],
    },
    "drivers_karachi": {
        "date": "2026-03-06",
        "data": {
            "target": "Karachi",
            "drivers": [
                {
                    "driver": "transport",
                    "score": 62,
                    "evidence": [
                        "Sea breeze reversal bringing inland pollution",
                        "Elevated PM2.5 plume from industrial corridor",
                    ],
                },
                {
                    "driver": "local_emissions",
                    "score": 48,
                    "evidence": [
                        "Vehicle emissions from Korangi Industrial Area",
                    ],
                },
            ],
        },
        "basis": {
            "description": "Driver attribution from watchlist",
            "sources": ["watchlist", "station_observations"],
            "driver_source": "scored",
        },
        "action_hint": "",
        "followups": ["Show Karachi stations", "Compare with yesterday"],
    },

    # ── aq_nearest_assets ──────────────────────────────────────────────
    "nearest_assets_fire_anchor": {
        "date": "2026-03-06",
        "data": {
            "anchor": {"lat": 31.45, "lon": 74.25},
            "radius_m": 5000,
            "assets": [
                {
                    "name": "Mayo Hospital",
                    "asset_type": "hospital",
                    "lat": 31.4520,
                    "lon": 74.2530,
                    "distance_m": 350,
                    "source": "OSM",
                    "osm_id": "node/123456",
                    "admin": {"district": "Lahore", "province": "Punjab"},
                },
                {
                    "name": "Government College University",
                    "asset_type": "university",
                    "lat": 31.4555,
                    "lon": 74.2600,
                    "distance_m": 1200,
                    "source": "OSM",
                    "osm_id": "way/789012",
                    "admin": {"district": "Lahore", "province": "Punjab"},
                },
                {
                    "name": "Lahore Grammar School",
                    "asset_type": "school",
                    "lat": 31.4600,
                    "lon": 74.2700,
                    "distance_m": 2300,
                    "source": "OSM",
                    "osm_id": "node/345678",
                    "admin": {"district": "Lahore", "province": "Punjab"},
                },
                {
                    "name": "Services Hospital",
                    "asset_type": "hospital",
                    "lat": 31.4480,
                    "lon": 74.2350,
                    "distance_m": 3100,
                    "source": "OSM",
                    "osm_id": "node/901234",
                    "admin": {"district": "Lahore", "province": "Punjab"},
                },
            ],
            "counts_by_type": {"hospital": 2, "university": 1, "school": 1},
            "notes": [],
            "status": "ok",
        },
        "basis": {
            "description": "Nearby civic assets from pre-seeded OpenStreetMap data (GCS Parquet)",
            "sources": ["OpenStreetMap"],
            "limitations": "OSM coverage varies; some facilities may be unmapped.",
        },
        "followups": ["Show satellite imagery for this area", "What's driving the pollution here?"],
    },
    "nearest_assets_hospitals_only": {
        "date": "2026-03-06",
        "data": {
            "anchor": {"lat": 31.45, "lon": 74.25},
            "radius_m": 5000,
            "assets": [
                {
                    "name": "Mayo Hospital",
                    "asset_type": "hospital",
                    "lat": 31.4520,
                    "lon": 74.2530,
                    "distance_m": 350,
                    "source": "OSM",
                    "osm_id": "node/123456",
                    "admin": {"district": "Lahore", "province": "Punjab"},
                },
                {
                    "name": "Services Hospital",
                    "asset_type": "hospital",
                    "lat": 31.4480,
                    "lon": 74.2350,
                    "distance_m": 3100,
                    "source": "OSM",
                    "osm_id": "node/901234",
                    "admin": {"district": "Lahore", "province": "Punjab"},
                },
            ],
            "counts_by_type": {"hospital": 2},
            "notes": [],
            "status": "ok",
        },
        "basis": {
            "description": "Nearby civic assets from pre-seeded OpenStreetMap data (GCS Parquet)",
            "sources": ["OpenStreetMap"],
        },
        "followups": ["Show satellite imagery for this area"],
    },
    "nearest_assets_schools_only": {
        "date": "2026-03-06",
        "data": {
            "anchor": {"lat": 31.45, "lon": 74.25},
            "radius_m": 5000,
            "assets": [
                {
                    "name": "Lahore Grammar School",
                    "asset_type": "school",
                    "lat": 31.4600,
                    "lon": 74.2700,
                    "distance_m": 2300,
                    "source": "OSM",
                    "osm_id": "node/345678",
                    "admin": {"district": "Lahore", "province": "Punjab"},
                },
                {
                    "name": "Aitchison College",
                    "asset_type": "school",
                    "lat": 31.4650,
                    "lon": 74.2800,
                    "distance_m": 3500,
                    "source": "OSM",
                    "osm_id": "node/567890",
                    "admin": {"district": "Lahore", "province": "Punjab"},
                },
            ],
            "counts_by_type": {"school": 2},
            "notes": [],
            "status": "ok",
        },
        "basis": {
            "description": "Nearby civic assets from pre-seeded OpenStreetMap data (GCS Parquet)",
            "sources": ["OpenStreetMap"],
        },
        "followups": ["Show satellite imagery for this area"],
    },
    "nearest_assets_empty": {
        "date": "2026-03-06",
        "data": {
            "anchor": {"lat": 31.45, "lon": 74.25},
            "radius_m": 1000,
            "assets": [],
            "counts_by_type": {},
            "notes": ["No factory found within 1000m of the anchor point."],
            "status": "no_results",
        },
        "basis": {
            "description": "Nearby civic assets from pre-seeded OpenStreetMap data (GCS Parquet)",
            "sources": ["OpenStreetMap"],
        },
        "followups": ["Expand search radius to 10 km"],
    },

    # ── aq_satellite_image ─────────────────────────────────────────────
    "sentinel_latest_ok": {
        "date": "2026-03-06",
        "data": {
            "status": "ok",
            "collection": "sentinel-2-l2a",
            "mode": "latest",
            "scene": {
                "scene_id": "S2B_MSIL2A_20260304T052659_N0511_R076_T43SCS_20260304T080000",
                "acquisition_date": "2026-03-04",
                "cloud_cover": 8.2,
                "processing_level": "L2A",
                "preview_url": "https://catalogue.dataspace.copernicus.eu/preview/S2B_20260304.jpg",
                "bbox": [74.1, 31.3, 74.5, 31.7],
            },
            "total_candidates": 5,
            "bbox": [74.15, 31.35, 74.55, 31.65],
            "notes": ["Latest low-cloud scene intersecting AOI (5 candidates in window)"],
        },
        "basis": {
            "description": "Sentinel-2 L2A catalog from Copernicus Data Space Ecosystem",
            "sources": ["Copernicus CDSE STAC"],
        },
        "followups": ["What civic assets are near this location?", "Show before and after imagery"],
    },
    "sentinel_nearest_date": {
        "date": "2026-03-06",
        "data": {
            "status": "ok",
            "collection": "sentinel-2-l2a",
            "mode": "nearest_to_date",
            "target_date": "2026-03-01",
            "scene": {
                "scene_id": "S2A_MSIL2A_20260302T053201_N0511_R105_T43SCS_20260302T090000",
                "acquisition_date": "2026-03-02",
                "cloud_cover": 12.5,
                "processing_level": "L2A",
                "preview_url": "https://catalogue.dataspace.copernicus.eu/preview/S2A_20260302.jpg",
                "bbox": [74.1, 31.3, 74.5, 31.7],
            },
            "total_candidates": 3,
            "bbox": [74.15, 31.35, 74.55, 31.65],
            "notes": ["Closest scene to 2026-03-01 (3 candidates)"],
        },
        "basis": {
            "description": "Sentinel-2 L2A catalog from Copernicus Data Space Ecosystem",
            "sources": ["Copernicus CDSE STAC"],
        },
        "followups": ["Show before and after imagery"],
    },
    "sentinel_before_after": {
        "date": "2026-03-06",
        "data": {
            "status": "ok",
            "collection": "sentinel-2-l2a",
            "mode": "before_after",
            "target_date": "2026-03-03",
            "before": {
                "scene_id": "S2A_MSIL2A_20260228T053201_before",
                "acquisition_date": "2026-02-28",
                "cloud_cover": 6.1,
                "processing_level": "L2A",
                "preview_url": "https://catalogue.dataspace.copernicus.eu/preview/S2A_before.jpg",
                "bbox": [74.1, 31.3, 74.5, 31.7],
            },
            "after": {
                "scene_id": "S2B_MSIL2A_20260304T052659_after",
                "acquisition_date": "2026-03-04",
                "cloud_cover": 8.2,
                "processing_level": "L2A",
                "preview_url": "https://catalogue.dataspace.copernicus.eu/preview/S2B_after.jpg",
                "bbox": [74.1, 31.3, 74.5, 31.7],
            },
            "total_candidates": 4,
            "bbox": [74.15, 31.35, 74.55, 31.65],
            "notes": ["Before: 2026-02-28", "After: 2026-03-04"],
        },
        "basis": {
            "description": "Sentinel-2 L2A catalog from Copernicus Data Space Ecosystem",
            "sources": ["Copernicus CDSE STAC"],
        },
        "followups": ["What civic assets are near this location?"],
    },
    "sentinel_no_scene": {
        "date": "2026-03-06",
        "data": {
            "status": "no_suitable_scene",
            "reason": "No Sentinel-2 L2A scene intersecting AOI with cloud cover <= 20% in 2026-03-05 to 2026-03-06",
            "collection": "sentinel-2-l2a",
            "bbox": [74.15, 31.35, 74.55, 31.65],
        },
        "basis": {
            "description": "Sentinel-2 L2A catalog from Copernicus Data Space Ecosystem",
            "sources": ["Copernicus CDSE STAC"],
        },
        "followups": ["Try with higher cloud cover threshold (50%)", "Expand the date range"],
    },
}
