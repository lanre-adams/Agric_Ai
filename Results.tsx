'use client';

import { useEffect, useRef, useState } from 'react';


interface VariationMapBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}


interface CropTimingContext {
  timing_phase?: string | null;
  timing_basis?: string | null;
  cover_screen_mode?: string | null;
  decline_expected?: boolean | null;
  profile_available?: boolean | null;
  canopy_expected_from_dap?: number | null;
  late_season_from_dap?: number | null;
}


interface CropContext {
  has_crop_context?: boolean;
  crop_type?: string | null;
  crop_key?: string | null;
  planting_date?: string | null;
  irrigation_type?: string | null;
  season_id?: string | null;
  observation_date?: string | null;
  days_after_planting?: number | null;
  crop_timing_context?: CropTimingContext | null;
  cover_screen_mode?: string | null;
  decline_expected?: boolean | null;
  context_warnings?: string[];
}


interface ResultsProps {
  data: {
    // Present on failure responses from report_agent.
    error?: string;
    error_code?: string;
    status?: string;

    title?: string;
    summary?: string;
    explanation?: string;
    action?: string;
    urgency?: string;
    severity?: string;
    color?: string;
    recommendation?: string;

    condition_signal?: string;

    // Legacy/internal field retained for persistence.
    stress_type?: string;

    possible_causes?: string[];
    corroborating_signals?: string[];

    attention_area?: string | null;
    attention_is_distinct?: boolean;
    attention_source?: string;
    hotspot_summary?: string;

    // ── Step 3 crop / season context ─────────────────────────────
    // Optional at every layer. A polygon-only analysis remains valid.
    crop_context?: CropContext | null;
    has_crop_context?: boolean;
    crop_type?: string | null;
    planting_date?: string | null;
    irrigation_type?: string | null;
    season_id?: string | null;
    days_after_planting?: number | null;
    timing_phase?: string | null;
    cover_screen_mode?: string | null;
    decline_expected?: boolean | null;

    // ── Scope ────────────────────────────────────────────────────
    assessment_scope?: 'whole_field' | 'partial_field' | 'local_only';
    assessment_scope_message?: string | null;

    // ── Coverage: two geometries, two questions ──────────────────
    field_coverage?: {
      clear_fraction?: number;
      visible_percent?: number;
      footprint_fraction?: number;
      valid_pixel_count?: number;
      total_pixel_count?: number;
      geometry?: string;
    };

    analysis_coverage?: {
      clear_fraction?: number;
      footprint_fraction?: number;
      valid_pixel_count?: number;
      total_pixel_count?: number;
      geometry?: string;
    };

    analysis_geometry?: {
      edge_excluded?: boolean;
      edge_buffer_m?: number;
      full_area_m2?: number;
      analysed_area_m2?: number;
      analysed_area_share?: number;
      reason?: string;
    };

    spatial_coverage?: {
      spatially_representative?: boolean;
      distribution_score?: number;
      eligible_zone_count?: number;
      observed_zone_count?: number;
      zone_coverage?: Record<
        string,
        {
          total_pixels?: number;
          observed_pixels?: number;
          valid_pixels?: number;
          clear_fraction?: number;
          eligible?: boolean;
          observed_for_distribution?: boolean;
        }
      >;
    };

    coverage_tier?: string;
    field_coverage_tier?: string;
    analysis_coverage_tier?: string;

    zone_analysis_supported?: boolean;
    eligible_zone_count?: number;
    min_zones_for_analysis?: number;

    // ── Acquisition identity ─────────────────────────────────────
    image_date?: string;
    image_id?: string;
    source_image_ids?: string[];
    source_tile_count?: number;
    datatake_id?: string;
    observation_datetime_utc?: string;

    // ── Same-date relative variation map ─────────────────────────
    variation_map_url?: string;
    variation_map_bounds?: VariationMapBounds;

    variation_map_info?: {
      map_type?: string;
      index?: string;
      index_native_scale_m?: number;
      analysis_scale_m?: number;
      field_median?: number;
      p05?: number;
      p95?: number;
      observed_half_range?: number;
      display_half_range?: number;
      spread_is_meaningful?: boolean;
      valid_pixel_count?: number;
      enough_pixels_for_variation?: boolean;
      spread_exceeds_noise?: boolean;
      cloud_no_data_color?: string;
      edge_excluded_color?: string;
      legend_low?: string;
      legend_middle?: string;
      legend_high?: string;
      legend_no_data?: string;
      legend_edge?: string;
      comparable_across_dates?: boolean;
      health_classification?: boolean;
      uniform_field_message?: string | null;
    };

    // TEMPORARY compatibility aliases. All point at the variation map.
    field_condition_map_url?: string;
    condition_map_bounds?: VariationMapBounds;
    stress_map_url?: string;
    stress_map_bounds?: VariationMapBounds;

    center?: {
      lat: number;
      lng: number;
    };

    farm_area?: {
      hectares?: number;
      acres?: number;
    };

    area_ha?: number;
    area_acres?: number;

    image_info?: {
      source?: string;
      image_id?: string;
      source_image_ids?: string[];
      source_tile_count?: number;
      mosaic_policy?: string;
      date?: string;
      datatake_id?: string;
      observation_datetime_utc?: string;

      image_age_days?: number;

      selected_is_latest_pass?: boolean;
      fallback_used?: boolean;
      no_recent_pass?: boolean;

      latest_pass_date?: string;
      latest_pass_datatake?: string;
      latest_pass_fraction?: number;

      // Granule-wide provenance only. NOT this field's cloud cover.
      source_granule_cloud_percent_mean?: number;

      valid_pixel_fraction?: number;
      valid_pixel_count?: number;

      field_clear_fraction?: number;
      field_footprint_fraction?: number;
      analysis_clear_fraction?: number;
      analysis_footprint_fraction?: number;

      coverage_tier?: string;
      coverage_tier_rule?: string;
      field_coverage_tier?: string;
      analysis_coverage_tier?: string;
      assessment_scope?: string;

      spatially_representative?: boolean;
      distribution_score?: number;
      observed_zone_count?: number;
      eligible_zone_count?: number;
      zone_analysis_supported?: boolean;

      analysis_scale_m?: number;
      index_method?: string;
      edge_buffer_m?: number;
      edge_excluded?: boolean;

      cloud_mask_method?: string;
      cloud_mask_threshold?: number;
      cloud_gap_policy?: string;
      map_observation_policy?: string;

      search_window_days?: number;
      selection_mode?: string;
      candidate_count?: number;
      clean_candidate_count?: number;
      recent_candidate_count?: number;
    };

    technical_details?: {
      ndvi?: number;
      ndmi?: number;

      // TEMPORARY legacy alias for NDMI.
      ndwi?: number;

      ndre?: number;
      savi?: number;
      gndvi?: number;

      condition_signal?: string;
      stress_type?: string;

      confidence?: number | string;
      cover_source?: string;

      attention_source?: string;
      attention_is_distinct?: boolean;
      attention_rule?: string;
      spatial_status?: string;
      assessment_scope_applied?: string;

      relative_low_area?: string | null;

      zone_values?: Record<string, number>;
      zone_pixel_counts?: Record<string, number>;
      zone_analysis_supported?: boolean;
      eligible_zone_count?: number;
      min_zones_for_analysis?: number;

      valid_pixel_fraction?: number;
      valid_pixel_count?: number;
      coverage_tier?: string;

      image_id?: string;
      source_image_ids?: string[];
      source_tile_count?: number;
      datatake_id?: string;
      observation_datetime_utc?: string;

      selection_mode?: string;
      selected_is_latest_pass?: boolean;
      fallback_used?: boolean;
      no_recent_pass?: boolean;

      latest_pass_date?: string;
      latest_pass_fraction?: number;

      image_age_days?: number;
      search_window_days?: number;

      candidate_count?: number;
      clean_candidate_count?: number;
      recent_candidate_count?: number;

      cloud_mask_method?: string;
      cloud_mask_threshold?: number;

      analysis_scale_m?: number;
      index_method?: string;
      edge_buffer_m?: number;
      edge_excluded?: boolean;

      data_source?: string;

      recent_condition_status?: string;

      recent_ndvi_composite?: number;
      recent_ndre_composite?: number;
      recent_ndmi_composite?: number;
      recent_savi_composite?: number;
      recent_gndvi_composite?: number;

      ndvi_delta_recent?: number;
      ndre_delta_recent?: number;
      ndmi_delta_recent?: number;
      savi_delta_recent?: number;
      gndvi_delta_recent?: number;

      // Step 3 technical crop fields.
      has_crop_context?: boolean;
      crop_type?: string | null;
      crop_key?: string | null;
      planting_date?: string | null;
      irrigation_type?: string | null;
      season_id?: string | null;
      crop_observation_date?: string | null;
      days_after_planting?: number | null;
      timing_phase?: string | null;
      timing_basis?: string | null;
      crop_profile_available?: boolean | null;
      cover_screen_mode?: string | null;
      decline_expected?: boolean | null;
      crop_context_warnings?: string[];
    };

    recent_comparison?: {
      recent_condition_status?: string;
    };
  };

  polygon?: number[][] | null;

  // Accepted so page.tsx callers do not break, but deliberately not
  // rendered until historical_service.py provides the comparison layer.
  trend?: {
    farm_id: string;
    farm_name?: string;
    trend_status?: string;
    trend_summary?: string;
  } | null;
}


// ── Formatting helpers ────────────────────────────────────────────

function formatArea(value?: number): string {
  if (value === undefined || value === null) return '—';

  if (value >= 100) return value.toFixed(0);
  if (value >= 10) return value.toFixed(1);

  return value.toFixed(2);
}


function formatCoord(
  lat?: number,
  lng?: number
): string | null {
  if (lat === undefined || lng === undefined) return null;

  const latDir = lat >= 0 ? 'N' : 'S';
  const lngDir = lng >= 0 ? 'E' : 'W';

  return `${Math.abs(lat).toFixed(4)}° ${latDir}, ${Math.abs(lng).toFixed(4)}° ${lngDir}`;
}


function formatDate(value?: string | null): string | null {
  if (!value) return null;

  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);

  if (match) {
    const [, year, month, day] = match;
    const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));

    return date.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    });
  }

  const parsed = new Date(value);

  if (Number.isNaN(parsed.getTime())) return value;

  return parsed.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}


function humanize(value?: string | null): string | null {
  if (!value) return null;

  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}


function formatDaysFromPlanting(value?: number | null): string | null {
  if (value === undefined || value === null) return null;

  if (value < 0) {
    return `${Math.abs(value)} days before planting`;
  }

  if (value === 0) {
    return 'Planting date';
  }

  return `${value} days after planting`;
}


const CROP_LABEL: Record<string, string> = {
  corn: 'Corn / maize',
  maize: 'Corn / maize',
  soybean: 'Soybean',
  soy: 'Soybean',
  wheat: 'Wheat',
  rice: 'Rice',
  sorghum: 'Sorghum',
  millet: 'Millet',
  cotton: 'Cotton',
  cowpea: 'Cowpea',
  cassava: 'Cassava',
};


const IRRIGATION_LABEL: Record<string, string> = {
  rainfed: 'Rainfed',
  center_pivot: 'Center pivot',
  'center pivot': 'Center pivot',
  centre_pivot: 'Center pivot',
  'centre pivot': 'Center pivot',
  drip: 'Drip',
  sprinkler: 'Sprinkler',
  furrow: 'Furrow',
  flood: 'Flood',
  other: 'Other',
};


// Values emitted by crop_context.py.
//
// "unknown" is deliberately not mapped. It means Tagintell does not
// currently have a crop calendar for this crop, not that the system
// failed. In that case the farmer-facing timing row is simply omitted.
const TIMING_PHASE_LABEL: Record<string, string> = {
  pre_planting: 'Before planting',
  establishment: 'Early growth',
  main_growth: 'Main growth',
  late_season: 'Late season',
};

const CROP_WARNING_LABEL: Record<string, string> = {
  no_timing_profile_for_crop:
    'No season calendar exists for this crop yet, so broad crop timing was not estimated',
};


const SIGNAL_LABEL: Record<string, string> = {
  moisture_condition: 'Moisture condition',
  chlorophyll_condition: 'Crop condition',
  vegetation_cover: 'Vegetation cover',
  general_vegetation_condition: 'Overall vegetation',
  early_signal: 'Early signal',
  no_warning_signal: 'No warning signal',
  not_assessed: 'Not assessed',
  supporting_vegetation_signal: 'Supporting vegetation',
  dense_canopy_masking: 'Dense canopy',
};


const ATTENTION_SOURCE_LABEL: Record<string, string> = {
  ndre: 'NDRE',
  ndvi_fallback: 'NDVI fallback',
  field_uniform: 'measured, field uniform',
  insufficient_clear_zones: 'not enough clear zones',
  insufficient_pixels_for_variation: 'too few usable pixels',
  field_too_small_for_zone_analysis: 'field too small for zone analysis',
  scope_local_only: 'whole-field comparison not supported',
  insufficient_data: 'insufficient data',
};

const RANKED_SOURCES = new Set(['ndre', 'ndvi_fallback']);


const VARIATION_PALETTE = [
  '#E8F5E9',
  '#C8E6C9',
  '#81C784',
  '#43A047',
  '#1B5E20',
];

const FALLBACK_NO_DATA_GRAY = '#9CA3AF';
const FALLBACK_EDGE_GRAY = '#D1D5DB';


const cardStyle = {
  background: 'rgba(255,255,255,0.03)',
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: '14px',
  padding: '16px',
  marginBottom: '12px',
};


const labelStyle = {
  fontSize: '10px',
  color: 'rgba(255,255,255,0.35)',
  textTransform: 'uppercase' as const,
  letterSpacing: '1.2px',
  marginBottom: '8px',
};


// ── Variation map overlaid on satellite imagery ───────────────────

function FieldVariationMap({
  imageUrl,
  bounds,
  polygon,
}: {
  imageUrl: string;
  bounds: VariationMapBounds;
  polygon?: number[][] | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!containerRef.current) return;

    const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;

    if (!token) {
      setFailed(true);
      return;
    }

    let map: any;

    (async () => {
      try {
        const mapboxgl = (await import('mapbox-gl')).default;

        mapboxgl.accessToken = token;

        map = new mapboxgl.Map({
          container: containerRef.current!,
          style: 'mapbox://styles/mapbox/satellite-v9',
          center: [
            (bounds.west + bounds.east) / 2,
            (bounds.south + bounds.north) / 2,
          ],
          zoom: 14,
          interactive: true,
          dragRotate: false,
        });

        map.on('load', () => {
          map.addSource('variation-image', {
            type: 'image',
            url: imageUrl,
            coordinates: [
              [bounds.west, bounds.north],
              [bounds.east, bounds.north],
              [bounds.east, bounds.south],
              [bounds.west, bounds.south],
            ],
          });

          map.addLayer({
            id: 'variation-image-layer',
            type: 'raster',
            source: 'variation-image',
            paint: {
              'raster-opacity': 0.88,
            },
          });

          if (polygon && polygon.length >= 3) {
            const first = polygon[0];
            const last = polygon[polygon.length - 1];

            const ring =
              first[0] === last[0] && first[1] === last[1]
                ? polygon
                : [...polygon, first];

            map.addSource('farm-boundary', {
              type: 'geojson',
              data: {
                type: 'Feature',
                geometry: {
                  type: 'Polygon',
                  coordinates: [ring],
                },
                properties: {},
              },
            });

            map.addLayer({
              id: 'farm-boundary-line',
              type: 'line',
              source: 'farm-boundary',
              paint: {
                'line-color': '#ffffff',
                'line-width': 2,
                'line-dasharray': [2, 1.5],
              },
            });
          }

          map.fitBounds(
            [
              [bounds.west, bounds.south],
              [bounds.east, bounds.north],
            ],
            {
              padding: 36,
              duration: 0,
            }
          );
        });

        map.on('error', () => setFailed(true));
      } catch {
        setFailed(true);
      }
    })();

    return () => {
      if (map) map.remove();
    };
  }, [imageUrl, bounds, polygon]);

  if (failed) {
    return (
      <div
        style={{
          borderRadius: '10px',
          overflow: 'hidden',
        }}
      >
        <img
          src={imageUrl}
          alt="Within-field variation map"
          style={{
            width: '100%',
            display: 'block',
            borderRadius: '10px',
          }}
        />
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '260px',
        borderRadius: '10px',
        overflow: 'hidden',
      }}
    />
  );
}


// ── Variation map legend ──────────────────────────────────────────

function VariationLegend({
  info,
  edgeExcluded,
}: {
  info?: ResultsProps['data']['variation_map_info'];
  edgeExcluded?: boolean;
}) {
  const noDataColor = info?.cloud_no_data_color || FALLBACK_NO_DATA_GRAY;
  const edgeColor = info?.edge_excluded_color || FALLBACK_EDGE_GRAY;

  const low = info?.legend_low || 'lower relative reading';
  const mid = info?.legend_middle || 'typical for this field on this date';
  const high = info?.legend_high || 'higher relative reading';

  const noDataText =
    info?.legend_no_data || 'obscured by cloud, haze or shadow';
  const edgeText = info?.legend_edge || 'field edge, not analysed';

  const comparable = info?.comparable_across_dates === true;

  const swatch = (color: string) => ({
    width: '12px',
    height: '12px',
    borderRadius: '3px',
    background: color,
    flexShrink: 0,
    border: '1px solid rgba(0,0,0,0.25)',
  });

  return (
    <div style={{ marginTop: '12px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          justifyContent: 'center',
        }}
      >
        <span
          style={{
            fontSize: '10px',
            color: 'rgba(255,255,255,0.4)',
          }}
        >
          Lower
        </span>

        <div
          style={{
            flex: 1,
            maxWidth: '200px',
            height: '8px',
            borderRadius: '4px',
            background: `linear-gradient(90deg, ${VARIATION_PALETTE.join(', ')})`,
          }}
        />

        <span
          style={{
            fontSize: '10px',
            color: 'rgba(255,255,255,0.4)',
          }}
        >
          Higher
        </span>
      </div>

      <div
        style={{
          textAlign: 'center',
          fontSize: '10px',
          color: 'rgba(255,255,255,0.35)',
          marginTop: '6px',
          lineHeight: 1.5,
        }}
      >
        Lighter areas have a {low}; darker areas a {high}. The middle of
        the scale is {mid}.
      </div>

      <div
        style={{
          display: 'flex',
          gap: '14px',
          justifyContent: 'center',
          flexWrap: 'wrap',
          marginTop: '10px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <div style={swatch(noDataColor)} />
          <span
            style={{
              fontSize: '10px',
              color: 'rgba(255,255,255,0.4)',
            }}
          >
            Gray: {noDataText}
          </span>
        </div>

        {edgeExcluded && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <div style={swatch(edgeColor)} />
            <span
              style={{
                fontSize: '10px',
                color: 'rgba(255,255,255,0.4)',
              }}
            >
              Lighter gray: {edgeText}
            </span>
          </div>
        )}
      </div>

      {!comparable && (
        <div
          style={{
            textAlign: 'center',
            fontSize: '10px',
            color: 'rgba(250,204,21,0.55)',
            marginTop: '10px',
            lineHeight: 1.5,
          }}
        >
          Colours are scaled to this field on this date only. They cannot
          be compared with the colours in another report. A lighter area
          does not by itself mean the crop is unhealthy.
        </div>
      )}
    </div>
  );
}


// ── Compass ───────────────────────────────────────────────────────

function CompassDirection({
  direction,
  scopeLimited,
}: {
  direction: string;
  scopeLimited: boolean;
}) {
  const dirMap: Record<string, { deg: number; label: string }> = {
    'northwest area of the farm': { deg: 315, label: 'NW' },
    'north area of the farm': { deg: 0, label: 'N' },
    'northeast area of the farm': { deg: 45, label: 'NE' },
    'west area of the farm': { deg: 270, label: 'W' },
    'central area of the farm': { deg: 0, label: 'C' },
    'east area of the farm': { deg: 90, label: 'E' },
    'southwest area of the farm': { deg: 225, label: 'SW' },
    'south area of the farm': { deg: 180, label: 'S' },
    'southeast area of the farm': { deg: 135, label: 'SE' },
  };

  const found = dirMap[direction] || { deg: 0, label: '?' };
  const isCenter = found.label === 'C' || found.label === '?';

  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '16px',
        }}
      >
        <div
          style={{
            position: 'relative',
            width: '64px',
            height: '64px',
            flexShrink: 0,
          }}
        >
          <svg viewBox="0 0 64 64" width="64" height="64">
            <circle
              cx="32"
              cy="32"
              r="30"
              fill="rgba(255,255,255,0.03)"
              stroke="rgba(255,255,255,0.1)"
              strokeWidth="1"
            />

            {['N', 'E', 'S', 'W'].map((d, i) => {
              const angle = i * 90 - 90;
              const x = 32 + 22 * Math.cos((angle * Math.PI) / 180);
              const y = 32 + 22 * Math.sin((angle * Math.PI) / 180);

              return (
                <text
                  key={d}
                  x={x}
                  y={y}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize="8"
                  fill="rgba(255,255,255,0.3)"
                  fontWeight="600"
                >
                  {d}
                </text>
              );
            })}

            <circle cx="32" cy="32" r="3" fill="rgba(255,255,255,0.2)" />

            {!isCenter && (
              <>
                <line
                  x1="32"
                  y1="32"
                  x2={32 + 20 * Math.sin((found.deg * Math.PI) / 180)}
                  y2={32 - 20 * Math.cos((found.deg * Math.PI) / 180)}
                  stroke="#f97316"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                />

                <circle
                  cx={32 + 20 * Math.sin((found.deg * Math.PI) / 180)}
                  cy={32 - 20 * Math.cos((found.deg * Math.PI) / 180)}
                  r="4"
                  fill="#f97316"
                />
              </>
            )}
          </svg>
        </div>

        <div>
          <div style={labelStyle}>Area to check</div>

          <div
            style={{
              fontSize: '15px',
              fontWeight: '600',
              color: '#f97316',
              textTransform: 'capitalize',
            }}
          >
            {direction}
          </div>
        </div>
      </div>

      {scopeLimited && (
        <div
          style={{
            fontSize: '10px',
            color: 'rgba(255,255,255,0.35)',
            marginTop: '10px',
            lineHeight: 1.5,
          }}
        >
          Compared among the parts of the field that were reliably
          observed in this image.
        </div>
      )}
    </div>
  );
}

const INDEX_SCALE_DESCRIPTION: Record<
  string,
  {
    low: string;
    high: string;
  }
> = {
  NDRE: {
    low: 'Lower red-edge vegetation signal',
    high: 'Higher red-edge vegetation signal',
  },

  NDMI: {
    low: 'Lower canopy moisture-related signal',
    high: 'Higher canopy moisture-related signal',
  },

  NDVI: {
    low: 'Lower green vegetation signal',
    high: 'Higher green vegetation signal',
  },

  SAVI: {
    low: 'Lower soil-adjusted vegetation signal',
    high: 'Higher soil-adjusted vegetation signal',
  },

  GNDVI: {
    low: 'Lower green-band vegetation signal',
    high: 'Higher green-band vegetation signal',
  },
};

// ── Measurement bar ───────────────────────────────────────────────

function MeasurementBar({
  label,
  indexName,
  value,
  min = -1,
  max = 1,
}: {
  label: string;
  indexName: string;
  value?: number;
  min?: number;
  max?: number;
}) {
  if (value === undefined || value === null) {
    return null;
  }

  const pct = Math.max(
    0,
    Math.min(
      100,
      ((value - min) / (max - min)) * 100
    )
  );

  const zeroPct = Math.max(
    0,
    Math.min(
      100,
      ((0 - min) / (max - min)) * 100
    )
  );

  const scaleDescription =
    INDEX_SCALE_DESCRIPTION[indexName];

  return (
    <div style={{ marginBottom: '20px' }}>
      {/* Measurement name and exact value */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          gap: '12px',
          marginBottom: '8px',
        }}
      >
        <span
          style={{
            fontSize: '12px',
            color: 'rgba(255,255,255,0.65)',
          }}
        >
          {label}{' '}

          <span
            style={{
              color: 'rgba(255,255,255,0.3)',
              fontSize: '10px',
            }}
          >
            {indexName}
          </span>
        </span>

        <span
          style={{
            fontSize: '14px',
            fontWeight: '700',
            color: 'rgba(255,255,255,0.9)',
            fontFamily: 'monospace',
          }}
        >
          {value.toFixed(3)}
        </span>
      </div>


      {/* Scientific index scale */}
      <div
        style={{
          position: 'relative',
          height: '10px',
          borderRadius: '5px',

          // Neutral visual track.
          // This deliberately avoids red-to-green colouring because
          // farther right does not universally mean healthier.
          background:
            'linear-gradient(90deg, rgba(148,163,184,0.30), rgba(255,255,255,0.14), rgba(148,163,184,0.30))',

          border:
            '1px solid rgba(255,255,255,0.12)',
        }}
      >
        {/* Zero reference line */}
        <div
          style={{
            position: 'absolute',
            left: `${zeroPct}%`,
            top: '-4px',
            bottom: '-4px',
            width: '1px',
            background: 'rgba(255,255,255,0.4)',
            transform: 'translateX(-50%)',
          }}
        />


        {/* Actual measured value */}
        <div
          style={{
            position: 'absolute',
            left: `${pct}%`,
            top: '50%',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            background: 'white',
            border: '2px solid #0d1a2e',
            transform:
              'translate(-50%, -50%)',
            boxShadow:
              '0 1px 5px rgba(0,0,0,0.45)',
          }}
        />
      </div>


      {/* Numerical scale */}
      <div
        style={{
          position: 'relative',
          height: '18px',
          marginTop: '5px',
          fontFamily: 'monospace',
          fontSize: '9px',
          color: 'rgba(255,255,255,0.35)',
        }}
      >
        <span
          style={{
            position: 'absolute',
            left: 0,
          }}
        >
          −1
        </span>

        <span
          style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
          }}
        >
          0
        </span>

        <span
          style={{
            position: 'absolute',
            right: 0,
          }}
        >
          +1
        </span>
      </div>


      {/* What the direction means scientifically */}
      {scaleDescription && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: '16px',
            marginTop: '2px',
            fontSize: '9px',
            color: 'rgba(255,255,255,0.3)',
            lineHeight: 1.4,
          }}
        >
          <span
            style={{
              maxWidth: '45%',
            }}
          >
            {scaleDescription.low}
          </span>

          <span
            style={{
              maxWidth: '45%',
              textAlign: 'right',
            }}
          >
            {scaleDescription.high}
          </span>
        </div>
      )}
    </div>
  );
}


// ── Main component ────────────────────────────────────────────────

export default function Results({
  data,
  polygon,
}: ResultsProps) {
  const [showTech, setShowTech] = useState(false);

  // ── Failure response ───────────────────────────────────────────
  if (data.error || data.status === 'failed') {
    const satelliteUnavailable =
      data.error_code === 'SATELLITE_DATA_UNAVAILABLE';

    const boundaryInvalid = data.error_code === 'BOUNDARY_INVALID';

    const title = satelliteUnavailable
      ? 'No suitable satellite image available'
      : boundaryInvalid
        ? 'Field boundary could not be analyzed'
        : 'Analysis could not be completed';

    const background = satelliteUnavailable
      ? 'rgba(250,204,21,0.07)'
      : 'rgba(148,163,184,0.08)';

    const border = satelliteUnavailable
      ? 'rgba(250,204,21,0.25)'
      : 'rgba(148,163,184,0.25)';

    const titleColor = satelliteUnavailable ? '#facc15' : '#cbd5e1';

    return (
      <div
        style={{
          ...cardStyle,
          background,
          border: `1px solid ${border}`,
        }}
      >
        <div
          style={{
            fontSize: '16px',
            fontWeight: '700',
            marginBottom: '8px',
            color: titleColor,
          }}
        >
          {title}
        </div>

        <div
          style={{
            fontSize: '13px',
            color: 'rgba(255,255,255,0.65)',
            lineHeight: 1.6,
          }}
        >
          {data.error || 'The analysis could not be completed.'}
        </div>
      </div>
    );
  }


  const conditionSignal =
    data.condition_signal ||
    data.technical_details?.condition_signal ||
    'not_assessed';

  const notAssessed = conditionSignal === 'not_assessed';


  const severityConfig = {
    none: {
      bg: 'rgba(34,214,122,0.1)',
      border: 'rgba(34,214,122,0.3)',
      text: '#22d67a',
      label: 'No warning',
    },

    mild: {
      bg: 'rgba(250,204,21,0.1)',
      border: 'rgba(250,204,21,0.3)',
      text: '#facc15',
      label: 'Watch',
    },

    moderate: {
      bg: 'rgba(249,115,22,0.1)',
      border: 'rgba(249,115,22,0.3)',
      text: '#f97316',
      label: 'Moderate',
    },

    severe: {
      bg: 'rgba(239,68,68,0.1)',
      border: 'rgba(239,68,68,0.3)',
      text: '#ef4444',
      label: 'Severe',
    },
  };


  const sev = notAssessed
    ? {
      bg: 'rgba(148,163,184,0.1)',
      border: 'rgba(148,163,184,0.3)',
      text: '#94a3b8',
      label: 'Not assessed',
    }
    : severityConfig[
    data.severity as keyof typeof severityConfig
    ] || severityConfig.moderate;


  const tech = data.technical_details || {};
  const imageInfo = data.image_info || {};
  const variationInfo = data.variation_map_info;
  const cropContext = data.crop_context || {};
  const cropTiming = cropContext.crop_timing_context || {};


  const ndre = tech.ndre;
  const ndmi = tech.ndmi ?? tech.ndwi;
  const ndvi = tech.ndvi;
  const savi = tech.savi;
  const gndvi = tech.gndvi;


  const hectares = data.farm_area?.hectares ?? data.area_ha;
  const acres = data.farm_area?.acres ?? data.area_acres;

  const coords = formatCoord(data.center?.lat, data.center?.lng);


  // ── Step 3 crop context ────────────────────────────────────────
  // Farmer-facing fields are simple facts. Technical modes remain in
  // Technical Details rather than becoming user-facing diagnoses.
  const hasCropContext =
    data.has_crop_context ??
    cropContext.has_crop_context ??
    tech.has_crop_context ??
    false;

  const cropType =
    data.crop_type ??
    cropContext.crop_type ??
    tech.crop_type ??
    null;

  const cropKey =
    cropContext.crop_key ??
    tech.crop_key ??
    null;

  const plantingDate =
    data.planting_date ??
    cropContext.planting_date ??
    tech.planting_date ??
    null;

  const irrigationType =
    data.irrigation_type ??
    cropContext.irrigation_type ??
    tech.irrigation_type ??
    null;

  const seasonId =
    data.season_id ??
    cropContext.season_id ??
    tech.season_id ??
    null;

  const cropObservationDate =
    cropContext.observation_date ??
    tech.crop_observation_date ??
    data.image_date ??
    imageInfo.date ??
    null;

  const daysAfterPlanting =
    data.days_after_planting ??
    cropContext.days_after_planting ??
    tech.days_after_planting ??
    null;

  const timingPhase =
    data.timing_phase ??
    cropTiming.timing_phase ??
    tech.timing_phase ??
    null;

  const timingBasis =
    cropTiming.timing_basis ??
    tech.timing_basis ??
    null;

  const profileAvailable =
    cropTiming.profile_available ??
    tech.crop_profile_available ??
    null;

  const coverScreenMode =
    data.cover_screen_mode ??
    cropContext.cover_screen_mode ??
    cropTiming.cover_screen_mode ??
    tech.cover_screen_mode ??
    null;

  const declineExpected =
    data.decline_expected ??
    cropContext.decline_expected ??
    cropTiming.decline_expected ??
    tech.decline_expected ??
    null;

  const cropWarnings =
    cropContext.context_warnings ??
    tech.crop_context_warnings ??
    [];

  const cropDisplay = cropType
    ? CROP_LABEL[cropType.toLowerCase()] || humanize(cropType)
    : null;

  const irrigationDisplay = irrigationType
    ? IRRIGATION_LABEL[irrigationType.toLowerCase()] || humanize(irrigationType)
    : null;

  const timingDisplay =
    timingPhase && TIMING_PHASE_LABEL[timingPhase.toLowerCase()]
      ? TIMING_PHASE_LABEL[timingPhase.toLowerCase()]
      : null;

  const dapDisplay = formatDaysFromPlanting(daysAfterPlanting);

  const farmerCropRows = [
    { label: 'Crop', value: cropDisplay },
    { label: 'Planting date', value: formatDate(plantingDate) },
    { label: 'Water management', value: irrigationDisplay },
    { label: 'Satellite observation', value: formatDate(cropObservationDate) },
    { label: 'Timing from planting', value: dapDisplay },
    { label: 'Broad crop timing', value: timingDisplay },
  ].filter(
    (row): row is { label: string; value: string } => Boolean(row.value)
  );


  // ── Scope ──────────────────────────────────────────────────────
  const assessmentScope =
    data.assessment_scope ||
    (imageInfo.assessment_scope as ResultsProps['data']['assessment_scope']);

  const scopeLimited =
    assessmentScope === 'partial_field' ||
    assessmentScope === 'local_only';

  const scopeMessage = data.assessment_scope_message;


  // ── Coverage ───────────────────────────────────────────────────
  const fieldClearFraction =
    data.field_coverage?.clear_fraction ??
    imageInfo.field_clear_fraction;

  const fieldCoveragePct =
    data.field_coverage?.visible_percent ??
    (fieldClearFraction !== undefined && fieldClearFraction !== null
      ? Math.round(fieldClearFraction * 100)
      : undefined);

  const analysisClearFraction =
    data.analysis_coverage?.clear_fraction ??
    imageInfo.analysis_clear_fraction ??
    imageInfo.valid_pixel_fraction ??
    tech.valid_pixel_fraction;

  const analysisCoveragePct =
    analysisClearFraction !== undefined && analysisClearFraction !== null
      ? Math.round(analysisClearFraction * 100)
      : undefined;

  const coverageTier =
    data.coverage_tier ?? imageInfo.coverage_tier ?? tech.coverage_tier;

  const fallbackUsed = imageInfo.fallback_used === true;
  const noRecentPass = imageInfo.no_recent_pass === true;

  const latestPassPct =
    imageInfo.latest_pass_fraction !== undefined &&
      imageInfo.latest_pass_fraction !== null
      ? Math.round(imageInfo.latest_pass_fraction * 100)
      : undefined;


  // ── Variation map ──────────────────────────────────────────────
  const variationMapUrl = data.variation_map_url;
  const variationBounds = data.variation_map_bounds;

  const spreadIsMeaningful =
    variationInfo?.spread_is_meaningful !== false;

  const uniformMessage = variationInfo?.uniform_field_message;


  // ── Zone analysis ──────────────────────────────────────────────
  const zoneAnalysisSupported =
    data.zone_analysis_supported ?? tech.zone_analysis_supported;

  const attentionSource =
    data.attention_source || tech.attention_source;

  const attentionSourceLabel = attentionSource
    ? ATTENTION_SOURCE_LABEL[attentionSource] || attentionSource
    : undefined;

  const rankingRan =
    attentionSource !== undefined && RANKED_SOURCES.has(attentionSource);


  const possibleCauses = data.possible_causes || [];

  const corroborating = (data.corroborating_signals || []).filter(
    (signal) => signal !== 'dense_canopy_masking'
  );

  const attentionArea = data.attention_area;

  const edgeExcluded =
    data.analysis_geometry?.edge_excluded ?? imageInfo.edge_excluded;

  const edgeBufferM =
    data.analysis_geometry?.edge_buffer_m ?? imageInfo.edge_buffer_m;


  return (
    <div style={{ color: 'white' }}>

      {/* ── Status ─────────────────────────────────────────────── */}

      <div
        style={{
          ...cardStyle,
          background: sev.bg,
          border: `1px solid ${sev.border}`,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '8px',
          }}
        >
          <div>
            <div
              style={{
                fontSize: '18px',
                fontWeight: '800',
                color: sev.text,
                lineHeight: 1.2,
              }}
            >
              {data.title}
            </div>

            <div
              style={{
                fontSize: '12px',
                color: 'rgba(255,255,255,0.5)',
                marginTop: '4px',
              }}
            >
              {notAssessed
                ? 'Assessment unavailable for this observation'
                : data.urgency === 'high'
                  ? 'Immediate attention recommended'
                  : data.urgency === 'medium'
                    ? 'Monitor closely'
                    : 'Continue regular monitoring'}
            </div>
          </div>

          <div
            style={{
              padding: '6px 14px',
              borderRadius: '20px',
              background: sev.border,
              fontSize: '12px',
              fontWeight: '700',
              color: sev.text,
              textTransform: 'uppercase',
              letterSpacing: '0.8px',
            }}
          >
            {sev.label}
          </div>
        </div>

        {scopeLimited && (
          <div
            style={{
              marginTop: '10px',
              paddingTop: '10px',
              borderTop: '1px solid rgba(255,255,255,0.08)',
              fontSize: '11px',
              color: 'rgba(250,204,21,0.8)',
              fontWeight: 600,
            }}
          >
            {assessmentScope === 'local_only'
              ? 'Partial assessment — observed areas only'
              : 'Partial assessment — clearly visible portion only'}
          </div>
        )}
      </div>


      {/* ── Satellite observation notice ──────────────────────── */}

      {(fallbackUsed || scopeLimited || noRecentPass) && (
        <div
          style={{
            ...cardStyle,
            background: 'rgba(250,204,21,0.06)',
            border: '1px solid rgba(250,204,21,0.22)',
          }}
        >
          <div
            style={{
              ...labelStyle,
              color: '#facc15',
              marginBottom: '6px',
            }}
          >
            {noRecentPass
              ? 'No recent satellite pass available'
              : fallbackUsed
                ? 'Previous satellite image used'
                : 'Partial satellite coverage'}
          </div>

          <div
            style={{
              fontSize: '13px',
              color: 'rgba(255,255,255,0.72)',
              lineHeight: 1.6,
            }}
          >
            {noRecentPass ? (
              <>
                No Sentinel-2 observation was available in the recent
                search period. This analysis uses the most recent suitable
                observation{imageInfo.date ? ` from ${imageInfo.date}` : ''}.
              </>
            ) : fallbackUsed ? (
              <>
                The most recent eligible satellite pass considered
                {imageInfo.latest_pass_date
                  ? ` from ${imageInfo.latest_pass_date}`
                  : ''}
                {latestPassPct !== undefined
                  ? ` had about ${latestPassPct}% usable field coverage`
                  : ' did not provide enough usable field coverage'}.
                {' '}This analysis uses a more suitable observation
                {imageInfo.date ? ` from ${imageInfo.date}` : ''}.
              </>
            ) : (
              scopeMessage || (
                <>
                  {fieldCoveragePct !== undefined
                    ? `About ${fieldCoveragePct}% of this field had a reliable satellite observation.`
                    : 'Only part of this field had a reliable satellite observation.'}
                  {' '}The findings describe the observed portion of the field.
                </>
              )
            )}

            {(fallbackUsed || noRecentPass) && scopeLimited && (
              <>
                {' '}
                {scopeMessage ||
                  (fieldCoveragePct !== undefined
                    ? `About ${fieldCoveragePct}% of the field had a reliable observation, so the findings apply to the observed portion.`
                    : 'The findings apply only to the reliably observed portion of the field.')}
              </>
            )}
          </div>
        </div>
      )}


      {/* ── Crop & management context ─────────────────────────── */}

      {hasCropContext && farmerCropRows.length > 0 && (
        <div
          style={{
            ...cardStyle,
            background: 'rgba(34,214,122,0.045)',
            border: '1px solid rgba(34,214,122,0.16)',
          }}
        >
          <div
            style={{
              ...labelStyle,
              color: '#22d67a',
              marginBottom: '10px',
            }}
          >
            Crop & management context
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
              gap: '10px 16px',
            }}
            className="crop-results-grid"
          >
            {farmerCropRows.map((row) => (
              <div key={row.label}>
                <div
                  style={{
                    fontSize: '10px',
                    color: 'rgba(255,255,255,0.32)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.7px',
                    marginBottom: '3px',
                  }}
                >
                  {row.label}
                </div>

                <div
                  style={{
                    fontSize: '13px',
                    color: 'rgba(255,255,255,0.82)',
                    lineHeight: 1.4,
                  }}
                >
                  {row.value}
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              marginTop: '12px',
              paddingTop: '10px',
              borderTop: '1px solid rgba(34,214,122,0.10)',
              fontSize: '10px',
              color: 'rgba(255,255,255,0.38)',
              lineHeight: 1.5,
            }}
          >
            These details help Tagintell interpret the satellite reading.
            The timing shown is a broad calendar context based on the
            supplied planting date and the selected satellite observation,
            not a measured growth stage.
          </div>
        </div>
      )}


      {/* ── Summary ───────────────────────────────────────────── */}

      {data.summary && (
        <div style={cardStyle}>
          <div style={labelStyle}>Summary</div>

          <p
            style={{
              margin: 0,
              fontSize: '14px',
              lineHeight: 1.6,
              color: 'rgba(255,255,255,0.85)',
            }}
          >
            {data.summary}
          </p>
        </div>
      )}


      {/* ── What the satellite found ──────────────────────────── */}

      {data.explanation && (
        <div style={cardStyle}>
          <div style={labelStyle}>What the satellite found</div>

          <p
            style={{
              margin: 0,
              fontSize: '14px',
              color: 'rgba(255,255,255,0.85)',
              lineHeight: 1.6,
            }}
          >
            {data.explanation}
          </p>
        </div>
      )}


      {/* ── Possible causes ───────────────────────────────────── */}

      {possibleCauses.length > 0 && (
        <div style={cardStyle}>
          <div style={labelStyle}>Possible reasons</div>

          <div
            style={{
              fontSize: '11px',
              color: 'rgba(255,255,255,0.35)',
              marginBottom: '10px',
              lineHeight: 1.5,
            }}
          >
            The satellite measured a condition, not a cause. These are
            possibilities to check on the ground.
          </div>

          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '6px',
            }}
          >
            {possibleCauses.map((cause) => (
              <span
                key={cause}
                style={{
                  padding: '5px 11px',
                  borderRadius: '999px',
                  background: 'rgba(255,255,255,0.05)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  fontSize: '12px',
                  color: 'rgba(255,255,255,0.65)',
                }}
              >
                {cause}
              </span>
            ))}
          </div>

          {corroborating.length > 0 && (
            <div
              style={{
                marginTop: '12px',
                paddingTop: '10px',
                borderTop: '1px solid rgba(255,255,255,0.06)',
                fontSize: '12px',
                color: 'rgba(255,255,255,0.5)',
              }}
            >
              Also low in this observation:{' '}
              {corroborating
                .map((signal) =>
                  SIGNAL_LABEL[signal] || signal.replace(/_/g, ' ')
                )
                .join(', ')}
            </div>
          )}
        </div>
      )}


      {/* ── Location / area / variation ──────────────────────── */}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '12px',
          marginBottom: '12px',
        }}
        className="location-variation-grid"
      >
        <div style={{ ...cardStyle, margin: 0 }}>
          <div style={labelStyle}>Location</div>

          <div
            style={{
              fontSize: '14px',
              fontWeight: '600',
              color: 'white',
              fontFamily: 'monospace',
              lineHeight: 1.4,
            }}
          >
            {coords || '—'}
          </div>

          <div
            style={{
              fontSize: '12px',
              color: 'rgba(255,255,255,0.4)',
              marginTop: '8px',
            }}
          >
            {formatArea(hectares)} ha
            {' · '}
            {formatArea(acres)} acres
          </div>
        </div>

        <div style={{ ...cardStyle, margin: 0 }}>
          {attentionArea ? (
            <CompassDirection
              direction={attentionArea}
              scopeLimited={scopeLimited}
            />
          ) : (
            <>
              <div style={labelStyle}>Field variation</div>

              <div
                style={{
                  fontSize: '13px',
                  color: 'rgba(255,255,255,0.55)',
                  lineHeight: 1.5,
                }}
              >
                {data.hotspot_summary ||
                  'No within-field comparison is available for this observation.'}
              </div>
            </>
          )}
        </div>
      </div>


      {/* ── Field variation map ───────────────────────────────── */}

      {variationMapUrl && (
        <div style={cardStyle}>
          <div
            style={{
              ...labelStyle,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span>Within-field variation map</span>

            <span
              style={{
                color: 'rgba(255,255,255,0.2)',
                fontSize: '9px',
              }}
            >
              {imageInfo.date
                ? `${imageInfo.date} observation`
                : 'Satellite observation'}
            </span>
          </div>

          {variationBounds ? (
            <FieldVariationMap
              imageUrl={variationMapUrl}
              bounds={variationBounds}
              polygon={polygon}
            />
          ) : (
            <div
              style={{
                borderRadius: '10px',
                overflow: 'hidden',
              }}
            >
              <img
                src={variationMapUrl}
                alt="Within-field variation map"
                style={{
                  width: '100%',
                  display: 'block',
                  borderRadius: '10px',
                }}
              />
            </div>
          )}

          <VariationLegend
            info={variationInfo}
            edgeExcluded={edgeExcluded === true}
          />

          {!spreadIsMeaningful && uniformMessage && (
            <div
              style={{
                marginTop: '10px',
                paddingTop: '10px',
                borderTop: '1px solid rgba(255,255,255,0.06)',
                fontSize: '11px',
                color: 'rgba(255,255,255,0.45)',
                lineHeight: 1.5,
              }}
            >
              {uniformMessage}
            </div>
          )}

          {edgeExcluded && edgeBufferM ? (
            <div
              style={{
                marginTop: '8px',
                fontSize: '10px',
                color: 'rgba(255,255,255,0.25)',
                lineHeight: 1.5,
              }}
            >
              A {edgeBufferM} m strip along the boundary is excluded from
              the analysis, because those pixels mix crop with roads, tree
              lines and headlands.
            </div>
          ) : null}
        </div>
      )}


      {/* ── What to do next ───────────────────────────────────── */}

      {data.action && (
        <div
          style={{
            ...cardStyle,
            background: 'rgba(34,214,122,0.05)',
            border: '1px solid rgba(34,214,122,0.15)',
          }}
        >
          <div style={{ ...labelStyle, color: '#22d67a' }}>
            What to do next
          </div>

          <p
            style={{
              margin: 0,
              fontSize: '14px',
              color: 'rgba(255,255,255,0.85)',
              lineHeight: 1.6,
            }}
          >
            {data.action}
          </p>

          {data.recommendation && data.recommendation !== data.action && (
            <p
              style={{
                margin: '10px 0 0',
                paddingTop: '10px',
                borderTop: '1px solid rgba(34,214,122,0.12)',
                fontSize: '13px',
                color: 'rgba(255,255,255,0.6)',
                lineHeight: 1.6,
              }}
            >
              {data.recommendation}
            </p>
          )}
        </div>
      )}


      {/* ── Measurements ──────────────────────────────────────── */}

      {!notAssessed && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, marginBottom: '14px' }}>
            Measurements
          </div>

          <MeasurementBar
            label="Red-edge vegetation signal"
            indexName="NDRE"
            value={ndre}
            min={-1}
            max={1}
          />

          <MeasurementBar
            label="Vegetation moisture-related signal"
            indexName="NDMI"
            value={ndmi}
            min={-1}
            max={1}
          />

          <MeasurementBar
            label="Green vegetation signal"
            indexName="NDVI"
            value={ndvi}
            min={-1}
            max={1}
          />

          <div
            style={{
              fontSize: '10px',
              color: 'rgba(255,255,255,0.3)',
              marginTop: '4px',
              lineHeight: 1.55,
            }}
          >
            These are satellite index values shown on their scientific numerical
            scale from −1 to +1. Moving farther right means a higher value for
            that specific index; it does not automatically mean the crop is
            healthier. Tagintell interprets the measurements together with the
            available crop context and other satellite signals.
            {scopeLimited
              ? ' These averages describe the reliably observed portion of the field only.'
              : ''}
          </div>
        </div>
      )}


      {/* ── Observation quality ───────────────────────────────── */}

      <div
        style={{
          ...cardStyle,
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '10px',
        }}
      >
        {[
          {
            label: 'Satellite',
            value: imageInfo.source,
          },
          {
            label: 'Observation date',
            value: imageInfo.date,
          },
          {
            label: 'Field observed',
            value:
              fieldCoveragePct !== undefined
                ? `${fieldCoveragePct}%`
                : undefined,
          },
          {
            label: 'Assessment',
            value:
              assessmentScope === 'whole_field'
                ? 'Whole field'
                : assessmentScope === 'partial_field'
                  ? 'Observed portion'
                  : assessmentScope === 'local_only'
                    ? 'Local areas only'
                    : undefined,
          },
          {
            label: 'Search period',
            value:
              imageInfo.search_window_days !== undefined
                ? `Past ${imageInfo.search_window_days} days`
                : undefined,
          },
          {
            label: 'Source tiles',
            value:
              (data.source_tile_count ?? imageInfo.source_tile_count) !== undefined
                ? String(data.source_tile_count ?? imageInfo.source_tile_count)
                : undefined,
          },
        ].map(({ label, value }) =>
          value ? (
            <div key={label}>
              <div
                style={{
                  fontSize: '10px',
                  color: 'rgba(255,255,255,0.3)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.8px',
                  marginBottom: '2px',
                }}
              >
                {label}
              </div>

              <div
                style={{
                  fontSize: '12px',
                  color: 'rgba(255,255,255,0.7)',
                }}
              >
                {value}
              </div>
            </div>
          ) : null
        )}
      </div>


      {/* ── Technical details ─────────────────────────────────── */}

      <div style={cardStyle}>
        <button
          onClick={() => setShowTech(!showTech)}
          style={{
            width: '100%',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            color: 'rgba(255,255,255,0.4)',
            fontSize: '11px',
            textTransform: 'uppercase',
            letterSpacing: '1.2px',
            padding: 0,
          }}
        >
          <span>Technical details</span>

          <span
            style={{
              fontSize: '14px',
              transition: 'transform 0.2s',
              transform: showTech ? 'rotate(180deg)' : 'none',
            }}
          >
            ▾
          </span>
        </button>


        {showTech && (
          <div style={{ marginTop: '12px' }}>
            <MeasurementBar
              label="Red-edge vegetation signal"
              indexName="NDRE"
              value={ndre}
              min={-1}
              max={1}
            />

            <MeasurementBar
              label="Vegetation moisture-related signal"
              indexName="NDMI"
              value={ndmi}
              min={-1}
              max={1}
            />

            <MeasurementBar
              label="Green vegetation signal"
              indexName="NDVI"
              value={ndvi}
              min={-1}
              max={1}
            />

            <MeasurementBar
              label="Soil-adjusted vegetation signal"
              indexName="SAVI"
              value={savi}
              min={-1}
              max={1}
            />

            <MeasurementBar
              label="Green-band vegetation signal"
              indexName="GNDVI"
              value={gndvi}
              min={-1}
              max={1}
            />


            {/* ── Step 3 crop technical context ─────────────── */}

            {hasCropContext && (
              <div
                style={{
                  marginTop: '14px',
                  padding: '12px',
                  background: 'rgba(34,214,122,0.035)',
                  borderRadius: '8px',
                  border: '1px solid rgba(34,214,122,0.10)',
                }}
              >
                <div style={{ ...labelStyle, marginBottom: '10px' }}>
                  Crop context used by the classifier
                </div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '9px 14px',
                  }}
                  className="crop-tech-grid"
                >
                  {[
                    { k: 'Crop type', v: cropType },
                    { k: 'Normalized crop key', v: cropKey },
                    { k: 'Planting date', v: plantingDate },
                    { k: 'Irrigation type', v: irrigationType },
                    { k: 'Season ID', v: seasonId },
                    { k: 'Observation date', v: cropObservationDate },
                    {
                      k: 'Days after planting',
                      v:
                        daysAfterPlanting !== null &&
                          daysAfterPlanting !== undefined
                          ? String(daysAfterPlanting)
                          : undefined,
                    },
                    { k: 'Timing phase', v: timingPhase },
                    { k: 'Timing basis', v: timingBasis },
                    {
                      k: 'Timing profile available',
                      v:
                        profileAvailable === true
                          ? 'Yes'
                          : profileAvailable === false
                            ? 'No'
                            : undefined,
                    },
                    { k: 'Cover screening mode', v: coverScreenMode },
                    {
                      k: 'Late-season decline expected',
                      v:
                        declineExpected === true
                          ? 'Yes — broad late-season window'
                          : declineExpected === false
                            ? 'No'
                            : 'Not determined',
                    },
                  ].map(({ k, v }) =>
                    v !== undefined && v !== null && v !== '' ? (
                      <div key={k}>
                        <div
                          style={{
                            fontSize: '9px',
                            color: 'rgba(255,255,255,0.25)',
                            marginBottom: '2px',
                          }}
                        >
                          {k}
                        </div>

                        <div
                          style={{
                            fontSize: '11px',
                            color: 'rgba(255,255,255,0.62)',
                            wordBreak: k === 'Season ID' ? 'break-all' : 'normal',
                          }}
                        >
                          {v}
                        </div>
                      </div>
                    ) : null
                  )}
                </div>

                {cropWarnings.length > 0 && (
                  <div
                    style={{
                      marginTop: '10px',
                      paddingTop: '8px',
                      borderTop: '1px solid rgba(255,255,255,0.06)',
                      fontSize: '10px',
                      color: 'rgba(250,204,21,0.6)',
                      lineHeight: 1.5,
                    }}
                  >
                    Context warnings:{' '}
                    {cropWarnings
                      .map(
                        (warning) =>
                          CROP_WARNING_LABEL[warning] ||
                          humanize(warning)
                      )
                      .join('; ')}
                  </div>
                )}
              </div>
            )}


            {/* ── Zone readings / pixel counts ───────────────── */}

            {zoneAnalysisSupported === false ? (
              <div
                style={{
                  marginTop: '14px',
                  padding: '10px 12px',
                  background: 'rgba(255,255,255,0.03)',
                  borderRadius: '8px',
                  border: '1px solid rgba(255,255,255,0.06)',
                  fontSize: '11px',
                  color: 'rgba(255,255,255,0.4)',
                  lineHeight: 1.5,
                }}
              >
                Within-field zone comparison is not available for this field.
                Only{' '}
                {data.eligible_zone_count ?? tech.eligible_zone_count ?? 0}{' '}
                of the grid cells hold enough area at the analysis resolution,
                and{' '}
                {data.min_zones_for_analysis ??
                  tech.min_zones_for_analysis ??
                  5}{' '}
                are required. Overall readings for the reliably observed area
                are still available.
              </div>
            ) : (
              tech.zone_values &&
              Object.keys(tech.zone_values).length > 0 && (
                <div
                  style={{
                    marginTop: '14px',
                    padding: '10px 12px',
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: '8px',
                    border: '1px solid rgba(255,255,255,0.06)',
                  }}
                >
                  <div style={{ ...labelStyle, marginBottom: '8px' }}>
                    Zone readings
                    {attentionSourceLabel
                      ? ` (${attentionSourceLabel})`
                      : ''}
                  </div>

                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(3, 1fr)',
                      gap: '4px',
                      fontFamily: 'monospace',
                      fontSize: '11px',
                    }}
                  >
                    {[
                      '0_0', '0_1', '0_2',
                      '1_0', '1_1', '1_2',
                      '2_0', '2_1', '2_2',
                    ].map((key) => (
                      <div
                        key={key}
                        style={{
                          padding: '6px',
                          textAlign: 'center',
                          borderRadius: '4px',
                          background: 'rgba(255,255,255,0.03)',
                          color:
                            tech.zone_values?.[key] !== undefined
                              ? 'rgba(255,255,255,0.7)'
                              : 'rgba(255,255,255,0.15)',
                        }}
                      >
                        <div>
                          {tech.zone_values?.[key]?.toFixed(3) ?? '—'}
                        </div>

                        {tech.zone_pixel_counts?.[key] !== undefined && (
                          <div
                            style={{
                              marginTop: '2px',
                              fontSize: '8px',
                              color: 'rgba(255,255,255,0.25)',
                            }}
                          >
                            {tech.zone_pixel_counts[key]} px
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  <div
                    style={{
                      marginTop: '8px',
                      fontSize: '10px',
                      color: 'rgba(255,255,255,0.25)',
                      lineHeight: 1.5,
                    }}
                  >
                    Cells shown as — either held too little area or were too
                    obscured to be ranked.
                  </div>

                  {!rankingRan && attentionSourceLabel && (
                    <div
                      style={{
                        marginTop: '6px',
                        fontSize: '10px',
                        color: 'rgba(250,204,21,0.5)',
                        lineHeight: 1.5,
                      }}
                    >
                      No zone was reported: {attentionSourceLabel}.
                    </div>
                  )}

                  {tech.relative_low_area && (
                    <div
                      style={{
                        marginTop: '8px',
                        fontSize: '11px',
                        color: 'rgba(255,255,255,0.4)',
                        textTransform: 'capitalize',
                      }}
                    >
                      Lowest zone: {tech.relative_low_area}
                    </div>
                  )}
                </div>
              )
            )}


            {/* ── Provenance ─────────────────────────────────── */}

            <div
              style={{
                marginTop: '12px',
                display: 'grid',
                gap: '8px',
              }}
            >
              {[
                {
                  k: 'Condition signal',
                  v: SIGNAL_LABEL[conditionSignal] || conditionSignal,
                },
                {
                  k: 'Assessment scope',
                  v: assessmentScope,
                },
                {
                  k: 'Confidence',
                  v:
                    tech.confidence !== undefined && tech.confidence !== null
                      ? String(tech.confidence)
                      : undefined,
                },
                {
                  k: 'Cover index used',
                  v: tech.cover_source,
                },
                {
                  k: 'Zone result',
                  v: attentionSourceLabel,
                },
                {
                  k: 'Datatake ID',
                  v: data.datatake_id ?? imageInfo.datatake_id,
                },
                {
                  k: 'Observation time (UTC)',
                  v:
                    data.observation_datetime_utc ??
                    imageInfo.observation_datetime_utc,
                },
                {
                  k: 'Source images',
                  v: (
                    data.source_image_ids ?? imageInfo.source_image_ids
                  )?.join(', '),
                },
                {
                  k: 'Field observed',
                  v:
                    fieldCoveragePct !== undefined
                      ? `${fieldCoveragePct}% of drawn boundary`
                      : undefined,
                },
                {
                  k: 'Analysis interior observed',
                  v:
                    analysisCoveragePct !== undefined
                      ? `${analysisCoveragePct}% of buffered interior`
                      : undefined,
                },
                {
                  k: 'Coverage tier',
                  v: coverageTier,
                },
                {
                  k: 'Edge buffer',
                  v:
                    edgeExcluded === true && edgeBufferM
                      ? `${edgeBufferM} m excluded`
                      : edgeExcluded === false
                        ? 'Not applied (field too small or thin)'
                        : undefined,
                },
                {
                  k: 'Analysis scale',
                  v:
                    (tech.analysis_scale_m ?? imageInfo.analysis_scale_m) !==
                      undefined
                      ? `${tech.analysis_scale_m ?? imageInfo.analysis_scale_m} m`
                      : undefined,
                },
                {
                  k: 'Valid pixels',
                  v:
                    imageInfo.valid_pixel_count !== undefined
                      ? String(imageInfo.valid_pixel_count)
                      : tech.valid_pixel_count !== undefined
                        ? String(tech.valid_pixel_count)
                        : undefined,
                },
                {
                  k: 'Image age',
                  v:
                    imageInfo.image_age_days !== undefined
                      ? `${imageInfo.image_age_days} days`
                      : undefined,
                },
                {
                  k: 'Observation selection',
                  v: imageInfo.selection_mode || tech.selection_mode,
                },
                {
                  k: 'Fallback used',
                  v:
                    imageInfo.fallback_used === true
                      ? 'Yes'
                      : imageInfo.fallback_used === false
                        ? 'No'
                        : undefined,
                },
                {
                  k: 'Latest pass date',
                  v: imageInfo.latest_pass_date,
                },
                {
                  k: 'Latest pass coverage',
                  v:
                    latestPassPct !== undefined
                      ? `${latestPassPct}%`
                      : undefined,
                },
                {
                  k: 'Search window',
                  v:
                    imageInfo.search_window_days !== undefined
                      ? `${imageInfo.search_window_days} days`
                      : undefined,
                },
                {
                  k: 'Source granule cloud (mean)',
                  v:
                    imageInfo.source_granule_cloud_percent_mean !== undefined
                      ? `${imageInfo.source_granule_cloud_percent_mean}% (whole tile, not this field)`
                      : undefined,
                },
                {
                  k: 'Data source',
                  v: tech.data_source,
                },
              ].map(({ k, v }) =>
                v ? (
                  <div key={k}>
                    <div
                      style={{
                        fontSize: '10px',
                        color: 'rgba(255,255,255,0.25)',
                        marginBottom: '2px',
                      }}
                    >
                      {k}
                    </div>

                    <div
                      style={{
                        fontSize: '11px',
                        color: 'rgba(255,255,255,0.6)',
                        fontFamily:
                          k === 'Datatake ID' || k === 'Source images'
                            ? 'monospace'
                            : 'inherit',
                        wordBreak: 'break-all',
                      }}
                    >
                      {v}
                    </div>
                  </div>
                ) : null
              )}
            </div>


            {tech.attention_rule && (
              <div
                style={{
                  marginTop: '12px',
                  fontSize: '10px',
                  color: 'rgba(255,255,255,0.25)',
                  lineHeight: 1.5,
                }}
              >
                {tech.attention_rule}
              </div>
            )}
          </div>
        )}
      </div>


      <style>{`
        @media (max-width: 700px) {
          .crop-results-grid,
          .crop-tech-grid,
          .location-variation-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}
