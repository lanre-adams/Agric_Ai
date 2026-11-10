'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import axios from 'axios';
import Link from 'next/link';

import {
  onAuthStateChanged,
  signOut,
  User,
} from 'firebase/auth';

import { auth } from '../lib/firebase';


const Map = dynamic(
  () => import('./components/Map'),
  { ssr: false }
);

const Results = dynamic(
  () => import('./components/Results'),
  { ssr: false }
);


// ── Types ────────────────────────────────────────────────────────

type CropTimingContext = {
  timing_phase?: string | null;
  timing_basis?: string | null;
  cover_screen_mode?: string | null;
  decline_expected?: boolean | null;
  profile_available?: boolean | null;
  canopy_expected_from_dap?: number | null;
  late_season_from_dap?: number | null;
};


type CropContext = {
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
};


type FarmAnalysisResponse = {
  // Present when the backend returns a failure object.
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

  // condition_signal is the safe user-facing classification.
  // stress_type is legacy/internal — kept for the database only.
  condition_signal?: string;
  stress_type?: string;

  possible_causes?: string[];
  corroborating_signals?: string[];

  // null is meaningful — no area was flagged.
  attention_area?: string | null;
  attention_is_distinct?: boolean;
  hotspot_summary?: string;

  // Step 3 crop / season context. All optional.
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

  // New field-condition naming.
  field_condition_map_url?: string;

  condition_map_bounds?: {
    west: number;
    south: number;
    east: number;
    north: number;
  };

  // TEMPORARY legacy aliases.
  stress_map_url?: string;

  stress_map_bounds?: {
    west: number;
    south: number;
    east: number;
    north: number;
  };

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

  // ── Satellite observation metadata ──────────────────────────
  image_info?: {
    source?: string;
    image_id?: string;
    date?: string;

    image_age_days?: number;

    selected_is_latest_pass?: boolean;
    fallback_used?: boolean;
    no_recent_pass?: boolean;

    latest_pass_date?: string;
    latest_pass_fraction?: number;

    // Granule-level Sentinel metadata. This is not farm cloud cover.
    cloud_cover_percent?: number;

    valid_pixel_fraction?: number;
    valid_pixel_count?: number;
    coverage_tier?: string;

    cloud_mask_method?: string;
    cloud_mask_threshold?: number;

    search_window_days?: number;
    selection_mode?: string;

    candidate_count?: number;
    clean_candidate_count?: number;
    recent_candidate_count?: number;

    search_window_start_utc?: string;
    query_end_date_exclusive_utc?: string;

    // TEMPORARY legacy fields still accepted by persistence.
    search_window_start?: string;
    search_window_end?: string;
  };

  // ── Technical / validation metadata ─────────────────────────
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

    relative_low_area?: string | null;

    zone_values?: Record<string, number>;
    zone_pixel_counts?: Record<string, number>;

    valid_pixel_fraction?: number;
    valid_pixel_count?: number;
    coverage_tier?: string;

    image_id?: string;

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
    data_source?: string;

    recent_condition_status?: string;

    recent_ndvi_composite?: number;
    recent_ndre_composite?: number;
    recent_ndmi_composite?: number;

    // TEMPORARY legacy alias.
    recent_ndwi_composite?: number;

    recent_savi_composite?: number;
    recent_gndvi_composite?: number;

    ndvi_delta_recent?: number;
    ndre_delta_recent?: number;
    ndmi_delta_recent?: number;

    // TEMPORARY legacy alias.
    ndwi_delta_recent?: number;

    savi_delta_recent?: number;
    gndvi_delta_recent?: number;

    // Step 3 technical crop fields may also be present here.
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
    recent_ndvi_composite?: number;
    recent_ndre_composite?: number;
    recent_ndmi_composite?: number;

    // TEMPORARY legacy alias.
    recent_ndwi_composite?: number;

    recent_savi_composite?: number;
    recent_gndvi_composite?: number;

    ndvi_delta_recent?: number;
    ndre_delta_recent?: number;
    ndmi_delta_recent?: number;

    // TEMPORARY legacy alias.
    ndwi_delta_recent?: number;

    savi_delta_recent?: number;
    gndvi_delta_recent?: number;

    recent_condition_status?: string;
  };
};


type FarmTrendResponse = {
  farm_id: string;
  farm_name?: string;

  trend_status:
  | 'no_history'
  | 'first_saved_check'
  | 'stable'
  | 'weaker'
  | 'improving'
  | 'mixed'
  | 'season_mismatch'
  | string;

  trend_summary: string;

  latest_analysis_id?: string;
  previous_analysis_id?: string;

  latest_analyzed_at?: string;
  previous_analyzed_at?: string;

  latest_season_id?: string | null;
  previous_season_id?: string | null;
  season_id?: string | null;
  decline_expected?: boolean | null;

  changes?: {
    ndre_change?: number | null;
    ndmi_change?: number | null;

    // TEMPORARY compatibility alias returned by the backend.
    ndwi_change?: number | null;

    ndvi_change?: number | null;
    savi_change?: number | null;
    severity_change?: number | null;
    days_after_planting_change?: number | null;
  };
};


type SavedFarm = {
  id: string;
  name: string;

  center_lat: number;
  center_lng: number;

  area_ha?: number;
  area_acres?: number;

  crop_type?: string | null;
  planting_date?: string | null;
  irrigation_type?: string | null;
  season_id?: string | null;

  created_at: string;
  updated_at: string;
};


type AnalysisPayload = {
  polygon: number[][];
  crop_type?: string;
  planting_date?: string;
  irrigation_type?: string;
  season_id?: string;
};


// ── Loading UI ───────────────────────────────────────────────────

const LOADING_STEPS = [
  'Validating farm boundary...',
  'Acquiring satellite imagery...',
  'Calculating crop indicators...',
  'Checking field variation...',
  'Preparing your report...',
];


const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  'http://localhost:8000';


function SatelliteLoader({
  step,
}: {
  step: number;
}) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '24px',
        padding: '40px 20px',
      }}
    >
      <div
        style={{
          position: 'relative',
          width: '200px',
          height: '200px',
        }}
      >
        <style>{`
          @keyframes orbit {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }

          @keyframes earthGlow {
            0%, 100% {
              filter: drop-shadow(0 0 8px rgba(34,214,122,0.3));
            }
            50% {
              filter: drop-shadow(0 0 22px rgba(34,214,122,0.75));
            }
          }

          @keyframes satFlash {
            0%, 100% {
              opacity: 1;
              filter: drop-shadow(0 0 3px rgba(34,214,122,0.4));
            }
            40% {
              opacity: 0.4;
              filter: drop-shadow(0 0 0px rgba(34,214,122,0));
            }
            50% {
              opacity: 1;
              filter: drop-shadow(0 0 10px rgba(34,214,122,1));
            }
            60% {
              opacity: 0.5;
              filter: drop-shadow(0 0 4px rgba(34,214,122,0.5));
            }
          }

          @keyframes beamFlash {
            0%, 100% { opacity: 0.15; }
            50% { opacity: 0.7; }
          }

          @keyframes signalPing {
            0% { r: 2; opacity: 1; }
            100% { r: 7; opacity: 0; }
          }

          .earth-globe {
            animation: earthGlow 3s ease-in-out infinite;
          }

          .orbit-group {
            animation: orbit 5s linear infinite;
            transform-origin: 100px 100px;
          }

          .sat-body {
            animation: satFlash 1.4s ease-in-out infinite;
          }

          .scan-beam {
            animation: beamFlash 1.4s ease-in-out infinite;
          }

          .ping-dot {
            animation: signalPing 1.4s ease-out infinite;
          }
        `}</style>

        <svg
          viewBox="0 0 200 200"
          width="200"
          height="200"
        >
          <defs>
            <radialGradient
              id="globeGrad"
              cx="40%"
              cy="35%"
              r="60%"
            >
              <stop offset="0%" stopColor="#1b6f50" />
              <stop offset="40%" stopColor="#0d3d6b" />
              <stop offset="100%" stopColor="#03081a" />
            </radialGradient>

            <clipPath id="globeClip">
              <circle cx="100" cy="100" r="46" />
            </clipPath>

            <linearGradient
              id="beamGrad"
              x1="0"
              x2="0"
              y1="0"
              y2="1"
            >
              <stop offset="0%" stopColor="#22d67a" stopOpacity="0.8" />
              <stop offset="100%" stopColor="#22d67a" stopOpacity="0" />
            </linearGradient>
          </defs>

          {[
            [18, 22],
            [170, 18],
            [185, 80],
            [160, 170],
            [25, 155],
            [140, 190],
            [55, 185],
            [190, 140],
          ].map(([x, y], i) => (
            <circle
              key={i}
              cx={x}
              cy={y}
              r="1"
              fill="white"
              opacity={0.2 + (i % 3) * 0.15}
            />
          ))}

          <ellipse
            cx="100"
            cy="100"
            rx="74"
            ry="30"
            fill="none"
            stroke="#22d67a"
            strokeWidth="0.8"
            opacity="0.18"
            strokeDasharray="6 5"
            transform="rotate(-20, 100, 100)"
          />

          <g className="earth-globe">
            <circle cx="100" cy="100" r="46" fill="url(#globeGrad)" />

            <g clipPath="url(#globeClip)">
              <ellipse cx="88" cy="90" rx="13" ry="17" fill="#1a5c2e" opacity="0.85" />
              <ellipse cx="108" cy="95" rx="9" ry="13" fill="#1a5c2e" opacity="0.75" />
              <ellipse cx="96" cy="115" rx="10" ry="8" fill="#1a5c2e" opacity="0.65" />
              <ellipse cx="118" cy="108" rx="6" ry="7" fill="#1a5c2e" opacity="0.55" />
              <ellipse cx="100" cy="88" rx="44" ry="7" fill="rgba(255,255,255,0.06)" />
            </g>

            <circle
              cx="100"
              cy="100"
              r="46"
              fill="none"
              stroke="#22d67a"
              strokeWidth="1.5"
              opacity="0.4"
            />

            <circle
              cx="100"
              cy="100"
              r="46"
              fill="none"
              stroke="#4fc3f7"
              strokeWidth="0.8"
              opacity="0.1"
            />
          </g>

          <g className="orbit-group">
            <g transform="translate(100, 26) rotate(20)">
              <line
                className="scan-beam"
                x1="0"
                y1="8"
                x2="-18"
                y2="58"
                stroke="url(#beamGrad)"
                strokeWidth="1.5"
              />

              <line
                className="scan-beam"
                x1="0"
                y1="8"
                x2="18"
                y2="58"
                stroke="url(#beamGrad)"
                strokeWidth="1.5"
              />

              <polygon
                className="scan-beam"
                points="0,8 -18,58 18,58"
                fill="url(#beamGrad)"
                opacity="0.25"
              />

              <circle
                className="ping-dot"
                cx="0"
                cy="55"
                r="2"
                fill="#22d67a"
              />

              <g className="sat-body">
                <rect
                  x="-7"
                  y="-5"
                  width="14"
                  height="10"
                  rx="2"
                  fill="#c8d8e8"
                  stroke="#22d67a"
                  strokeWidth="0.8"
                />

                <rect
                  x="-4"
                  y="-3"
                  width="8"
                  height="6"
                  rx="1"
                  fill="#1e293b"
                  opacity="0.7"
                />

                <rect
                  x="-24"
                  y="-4"
                  width="15"
                  height="8"
                  rx="1.5"
                  fill="#1e40af"
                  stroke="#22d67a"
                  strokeWidth="0.8"
                />

                <line x1="-22" y1="-4" x2="-22" y2="4" stroke="#60a5fa" strokeWidth="0.5" opacity="0.7" />
                <line x1="-17" y1="-4" x2="-17" y2="4" stroke="#60a5fa" strokeWidth="0.5" opacity="0.7" />
                <line x1="-12" y1="-4" x2="-12" y2="4" stroke="#60a5fa" strokeWidth="0.5" opacity="0.7" />

                <rect
                  x="9"
                  y="-4"
                  width="15"
                  height="8"
                  rx="1.5"
                  fill="#1e40af"
                  stroke="#22d67a"
                  strokeWidth="0.8"
                />

                <line x1="11" y1="-4" x2="11" y2="4" stroke="#60a5fa" strokeWidth="0.5" opacity="0.7" />
                <line x1="16" y1="-4" x2="16" y2="4" stroke="#60a5fa" strokeWidth="0.5" opacity="0.7" />
                <line x1="21" y1="-4" x2="21" y2="4" stroke="#60a5fa" strokeWidth="0.5" opacity="0.7" />

                <line
                  x1="0"
                  y1="5"
                  x2="0"
                  y2="11"
                  stroke="#9ca3af"
                  strokeWidth="1.2"
                />

                <ellipse
                  cx="0"
                  cy="12"
                  rx="5"
                  ry="2"
                  fill="none"
                  stroke="#22d67a"
                  strokeWidth="1"
                />

                <circle cx="6" cy="-4" r="1.8" fill="#22d67a" opacity="0.9" />
              </g>
            </g>
          </g>
        </svg>
      </div>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '12px',
          width: '100%',
          maxWidth: '320px',
        }}
      >
        {LOADING_STEPS.map((s, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              width: '100%',
              opacity: i <= step ? 1 : 0.3,
              transition: 'opacity 0.5s ease',
            }}
          >
            <div
              style={{
                width: '20px',
                height: '20px',
                borderRadius: '50%',
                flexShrink: 0,
                background:
                  i < step
                    ? '#22d67a'
                    : i === step
                      ? 'transparent'
                      : 'rgba(255,255,255,0.1)',
                border:
                  i === step
                    ? '2px solid #22d67a'
                    : i < step
                      ? 'none'
                      : '2px solid rgba(255,255,255,0.2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '11px',
              }}
            >
              {i < step && (
                <span style={{ color: '#03081a', fontWeight: 'bold' }}>
                  ✓
                </span>
              )}

              {i === step && (
                <div
                  style={{
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    background: '#22d67a',
                  }}
                />
              )}
            </div>

            <span
              style={{
                fontSize: '13px',
                color:
                  i === step
                    ? '#22d67a'
                    : i < step
                      ? 'rgba(255,255,255,0.7)'
                      : 'rgba(255,255,255,0.3)',
                fontFamily: 'monospace',
              }}
            >
              {s}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}


// ── Decorative background ────────────────────────────────────────

function SatelliteBackground() {
  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 0,
        overflow: 'hidden',
      }}
    >
      <style>{`
        @keyframes floatSat1 {
          0%, 100% { transform: translate(0,0) rotate(15deg); }
          50% { transform: translate(-20px,30px) rotate(25deg); }
        }

        @keyframes floatSat2 {
          0%, 100% { transform: translate(0,0) rotate(-20deg); }
          50% { transform: translate(30px,-20px) rotate(-30deg); }
        }

        @keyframes twinkle {
          0%, 100% { opacity: 0.8; }
          50% { opacity: 0.2; }
        }
      `}</style>

      {[...Array(40)].map((_, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            width: i % 5 === 0 ? '2px' : '1px',
            height: i % 5 === 0 ? '2px' : '1px',
            background: 'white',
            borderRadius: '50%',
            left: `${(i * 37 + 13) % 100}%`,
            top: `${(i * 53 + 7) % 100}%`,
            opacity: 0.3 + (i % 5) * 0.1,
            animation: `twinkle ${2 + (i % 4)}s ease-in-out infinite`,
            animationDelay: `${(i * 0.3) % 3}s`,
          }}
        />
      ))}

      <svg
        style={{
          position: 'absolute',
          top: '8%',
          right: '5%',
          opacity: 0.06,
          animation: 'floatSat1 8s ease-in-out infinite',
        }}
        width="60"
        height="30"
        viewBox="0 0 60 30"
      >
        <rect x="20" y="10" width="20" height="10" fill="white" rx="2" />
        <rect x="2" y="12" width="16" height="6" fill="white" rx="1" />
        <rect x="42" y="12" width="16" height="6" fill="white" rx="1" />
      </svg>

      <svg
        style={{
          position: 'absolute',
          bottom: '15%',
          left: '3%',
          opacity: 0.05,
          animation: 'floatSat2 10s ease-in-out infinite',
        }}
        width="50"
        height="25"
        viewBox="0 0 50 25"
      >
        <rect x="17" y="8" width="16" height="9" fill="white" rx="2" />
        <rect x="2" y="10" width="13" height="5" fill="white" rx="1" />
        <rect x="35" y="10" width="13" height="5" fill="white" rx="1" />
      </svg>

      <svg
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          opacity: 0.03,
        }}
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <pattern
            id="grid"
            width="60"
            height="60"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 60 0 L 0 0 0 60"
              fill="none"
              stroke="white"
              strokeWidth="0.5"
            />
          </pattern>
        </defs>

        <rect width="100%" height="100%" fill="url(#grid)" />
      </svg>
    </div>
  );
}


// ── Authentication modal ─────────────────────────────────────────

function AuthRequiredModal({
  onClose,
}: {
  onClose: () => void;
}) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.72)',
        zIndex: 120,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
      }}
    >
      <div
        style={{
          background: '#0d1a2e',
          border: '1px solid rgba(34,214,122,0.3)',
          borderRadius: '16px',
          padding: '24px',
          width: '100%',
          maxWidth: '390px',
          boxShadow: '0 24px 80px rgba(0,0,0,0.45)',
        }}
      >
        <div
          style={{
            fontSize: '18px',
            fontWeight: '800',
            marginBottom: '10px',
            color: 'white',
          }}
        >
          Save this farm to your account
        </div>

        <p
          style={{
            fontSize: '13px',
            color: 'rgba(255,255,255,0.62)',
            lineHeight: 1.6,
            margin: '0 0 18px',
          }}
        >
          You can analyze a farm without an account. To save farms, keep
          analysis history, and track changes over time, please create an
          account or log in.
        </p>

        <div style={{ display: 'grid', gap: '10px' }}>
          <Link
            href="/signup?continueSave=1"
            style={{
              display: 'block',
              textAlign: 'center',
              padding: '12px',
              borderRadius: '10px',
              background: 'linear-gradient(135deg, #22d67a, #16a85c)',
              color: '#03081a',
              textDecoration: 'none',
              fontSize: '14px',
              fontWeight: 800,
            }}
          >
            Create account
          </Link>

          <Link
            href="/login?continueSave=1"
            style={{
              display: 'block',
              textAlign: 'center',
              padding: '12px',
              borderRadius: '10px',
              border: '1px solid rgba(255,255,255,0.14)',
              background: 'rgba(255,255,255,0.04)',
              color: 'white',
              textDecoration: 'none',
              fontSize: '14px',
              fontWeight: 700,
            }}
          >
            Log in
          </Link>

          <button
            onClick={onClose}
            style={{
              padding: '10px',
              borderRadius: '10px',
              border: 'none',
              background: 'transparent',
              color: 'rgba(255,255,255,0.45)',
              cursor: 'pointer',
              fontSize: '13px',
            }}
          >
            Continue without saving
          </button>
        </div>
      </div>
    </div>
  );
}


// ── Save farm modal ──────────────────────────────────────────────

function SaveFarmModal({
  onSave,
  onClose,
  defaultName,
}: {
  onSave: (name: string) => void;
  onClose: () => void;
  defaultName: string;
}) {
  const [name, setName] = useState(defaultName);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
      }}
    >
      <div
        style={{
          background: '#0d1a2e',
          border: '1px solid rgba(34,214,122,0.3)',
          borderRadius: '16px',
          padding: '24px',
          width: '100%',
          maxWidth: '360px',
        }}
      >
        <div
          style={{
            fontSize: '16px',
            fontWeight: '700',
            marginBottom: '16px',
            color: 'white',
          }}
        >
          💾 Save This Farm
        </div>

        <div
          style={{
            fontSize: '12px',
            color: 'rgba(255,255,255,0.4)',
            marginBottom: '8px',
          }}
        >
          Give this farm a name so you can find it later
        </div>

        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. North Field, Kano Farm 1"
          style={{
            width: '100%',
            padding: '10px 12px',
            borderRadius: '8px',
            border: '1px solid rgba(255,255,255,0.15)',
            background: 'rgba(255,255,255,0.08)',
            color: 'white',
            fontSize: '14px',
            outline: 'none',
            boxSizing: 'border-box',
            marginBottom: '16px',
          }}
          autoFocus
          onKeyDown={(e) =>
            e.key === 'Enter' &&
            name.trim() &&
            onSave(name.trim())
          }
        />

        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            onClick={onClose}
            style={{
              flex: 1,
              padding: '10px',
              borderRadius: '8px',
              border: '1px solid rgba(255,255,255,0.1)',
              background: 'transparent',
              color: 'rgba(255,255,255,0.5)',
              cursor: 'pointer',
              fontSize: '14px',
            }}
          >
            Cancel
          </button>

          <button
            onClick={() => name.trim() && onSave(name.trim())}
            disabled={!name.trim()}
            style={{
              flex: 2,
              padding: '10px',
              borderRadius: '8px',
              border: 'none',
              background: name.trim()
                ? 'linear-gradient(135deg, #22d67a, #16a85c)'
                : 'rgba(255,255,255,0.05)',
              color: name.trim()
                ? '#03081a'
                : 'rgba(255,255,255,0.3)',
              cursor: name.trim() ? 'pointer' : 'not-allowed',
              fontSize: '14px',
              fontWeight: '700',
            }}
          >
            Save Farm
          </button>
        </div>
      </div>
    </div>
  );
}


// ── Saved farms panel ────────────────────────────────────────────

function MyFarmsPanel({
  farms,
  onSelect,
  onDelete,
  onClose,
  loading,
}: {
  farms: SavedFarm[];
  onSelect: (farm: SavedFarm) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
  loading: boolean;
}) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
      }}
    >
      <div
        style={{
          background: '#0d1a2e',
          border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: '16px',
          width: '100%',
          maxWidth: '480px',
          maxHeight: '80vh',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            padding: '18px 20px',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div
            style={{
              fontSize: '16px',
              fontWeight: '700',
              color: 'white',
            }}
          >
            🌾 My Saved Farms
          </div>

          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: 'rgba(255,255,255,0.4)',
              cursor: 'pointer',
              fontSize: '20px',
              lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        <div
          style={{
            overflowY: 'auto',
            flex: 1,
            padding: '12px',
          }}
        >
          {loading && (
            <div
              style={{
                textAlign: 'center',
                color: 'rgba(255,255,255,0.3)',
                padding: '40px',
                fontSize: '13px',
              }}
            >
              Loading farms...
            </div>
          )}

          {!loading && farms.length === 0 && (
            <div
              style={{
                textAlign: 'center',
                color: 'rgba(255,255,255,0.3)',
                padding: '40px',
                fontSize: '13px',
              }}
            >
              <div style={{ fontSize: '32px', marginBottom: '12px' }}>
                🌱
              </div>

              No saved farms yet. Draw a boundary and save your first farm.
            </div>
          )}

          {!loading &&
            farms.map((farm) => (
              <div
                key={farm.id}
                style={{
                  padding: '14px',
                  borderRadius: '10px',
                  border: '1px solid rgba(255,255,255,0.06)',
                  marginBottom: '8px',
                  background: 'rgba(255,255,255,0.02)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '10px',
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: '14px',
                      fontWeight: '600',
                      color: 'white',
                      marginBottom: '4px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {farm.name}
                  </div>

                  <div
                    style={{
                      fontSize: '11px',
                      color: 'rgba(255,255,255,0.35)',
                    }}
                  >
                    {farm.area_ha
                      ? `${farm.area_ha.toFixed(1)} ha · `
                      : ''}

                    {farm.crop_type
                      ? `${farm.crop_type} · `
                      : ''}

                    Saved {new Date(farm.updated_at).toLocaleDateString()}
                  </div>
                </div>

                <div
                  style={{
                    display: 'flex',
                    gap: '8px',
                    flexShrink: 0,
                  }}
                >
                  <button
                    onClick={() => onSelect(farm)}
                    style={{
                      padding: '7px 14px',
                      borderRadius: '7px',
                      border: 'none',
                      background: 'linear-gradient(135deg, #22d67a, #16a85c)',
                      color: '#03081a',
                      cursor: 'pointer',
                      fontSize: '12px',
                      fontWeight: '700',
                    }}
                  >
                    Load
                  </button>

                  <button
                    onClick={() => onDelete(farm.id)}
                    style={{
                      padding: '7px 10px',
                      borderRadius: '7px',
                      border: '1px solid rgba(239,68,68,0.3)',
                      background: 'rgba(239,68,68,0.1)',
                      color: '#fca5a5',
                      cursor: 'pointer',
                      fontSize: '12px',
                    }}
                  >
                    🗑
                  </button>
                </div>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}


// ── Optional crop context form ───────────────────────────────────

function CropContextForm({
  cropType,
  plantingDate,
  irrigationType,
  onCropTypeChange,
  onPlantingDateChange,
  onIrrigationTypeChange,
}: {
  cropType: string;
  plantingDate: string;
  irrigationType: string;
  onCropTypeChange: (value: string) => void;
  onPlantingDateChange: (value: string) => void;
  onIrrigationTypeChange: (value: string) => void;
}) {
  const timingIncomplete =
    (cropType && !plantingDate) ||
    (!cropType && plantingDate);

  return (
    <div
      style={{
        marginTop: '14px',
        padding: '16px',
        borderRadius: '12px',
        border: '1px solid rgba(34,214,122,0.16)',
        background: 'rgba(34,214,122,0.045)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '10px',
          flexWrap: 'wrap',
          marginBottom: '6px',
        }}
      >
        <div
          style={{
            fontSize: '14px',
            fontWeight: 700,
            color: 'white',
          }}
        >
          🌱 Crop & Season Details
        </div>

        <span
          style={{
            fontSize: '10px',
            fontWeight: 800,
            letterSpacing: '0.6px',
            textTransform: 'uppercase',
            color: '#22d67a',
            border: '1px solid rgba(34,214,122,0.25)',
            background: 'rgba(34,214,122,0.08)',
            padding: '3px 8px',
            borderRadius: '999px',
          }}
        >
          Optional
        </span>
      </div>

      <p
        style={{
          margin: '0 0 14px',
          fontSize: '12px',
          lineHeight: 1.55,
          color: 'rgba(255,255,255,0.48)',
        }}
      >
        Add what you know to help Tagintell interpret the satellite
        observation in the context of this crop. You can leave everything
        blank and analyze with only the farm boundary.
      </p>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          gap: '10px',
        }}
        className="crop-context-grid"
      >
        <label style={{ display: 'grid', gap: '6px' }}>
          <span
            style={{
              fontSize: '11px',
              color: 'rgba(255,255,255,0.55)',
              fontWeight: 600,
            }}
          >
            Crop
          </span>

          <select
            value={cropType}
            onChange={(e) => onCropTypeChange(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 11px',
              borderRadius: '8px',
              border: '1px solid rgba(255,255,255,0.12)',
              background: '#0d1a2e',
              color: 'white',
              fontSize: '13px',
              outline: 'none',
            }}
          >
            <option value="">Not specified</option>
            <option value="corn">Corn / maize</option>
            <option value="soybean">Soybean</option>
            <option value="wheat">Wheat</option>
            <option value="rice">Rice</option>
            <option value="sorghum">Sorghum</option>
            <option value="millet">Millet</option>
            <option value="cotton">Cotton</option>
            <option value="cowpea">Cowpea</option>
            <option value="cassava">Cassava</option>
          </select>
        </label>

        <label style={{ display: 'grid', gap: '6px' }}>
          <span
            style={{
              fontSize: '11px',
              color: 'rgba(255,255,255,0.55)',
              fontWeight: 600,
            }}
          >
            Planting date
          </span>

          <input
            type="date"
            value={plantingDate}
            onChange={(e) => onPlantingDateChange(e.target.value)}
            style={{
              width: '100%',
              padding: '9px 11px',
              borderRadius: '8px',
              border: '1px solid rgba(255,255,255,0.12)',
              background: '#0d1a2e',
              color: 'white',
              fontSize: '13px',
              outline: 'none',
              boxSizing: 'border-box',
              colorScheme: 'dark',
            }}
          />
        </label>

        <label style={{ display: 'grid', gap: '6px' }}>
          <span
            style={{
              fontSize: '11px',
              color: 'rgba(255,255,255,0.55)',
              fontWeight: 600,
            }}
          >
            Water management
          </span>

          <select
            value={irrigationType}
            onChange={(e) => onIrrigationTypeChange(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 11px',
              borderRadius: '8px',
              border: '1px solid rgba(255,255,255,0.12)',
              background: '#0d1a2e',
              color: 'white',
              fontSize: '13px',
              outline: 'none',
            }}
          >
            <option value="">Not specified</option>
            <option value="rainfed">Rainfed</option>
            <option value="center_pivot">Center pivot</option>
            <option value="drip">Drip</option>
            <option value="sprinkler">Sprinkler</option>
            <option value="furrow">Furrow</option>
            <option value="flood">Flood</option>
            <option value="other">Other</option>
          </select>
        </label>
      </div>

      {timingIncomplete && (
        <div
          style={{
            marginTop: '10px',
            fontSize: '11px',
            lineHeight: 1.5,
            color: '#facc15',
          }}
        >
          Crop and planting date work best together for timing context. You
          can still analyze now; Tagintell will only use the information you
          supplied.
        </div>
      )}
    </div>
  );
}


// ── Main page ────────────────────────────────────────────────────

export default function Home() {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [showAuthModal, setShowAuthModal] = useState(false);

  const [coordinates, setCoordinates] = useState<number[][] | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);

  const [results, setResults] = useState<FarmAnalysisResponse | null>(null);
  const [trend, setTrend] = useState<FarmTrendResponse | null>(null);

  // Used for network/HTTP problems where no structured Farm Watch
  // response was received. Structured backend analysis failures stay
  // in `results` and are rendered by Results.tsx.
  const [error, setError] = useState<string | null>(null);

  const [savedFarms, setSavedFarms] = useState<SavedFarm[]>([]);
  const [showMyFarms, setShowMyFarms] = useState(false);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [farmsLoading, setFarmsLoading] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  const [activeFarmId, setActiveFarmId] = useState<string | null>(null);
  const [loadFarmTrigger, setLoadFarmTrigger] = useState<number[][] | null>(null);

  // Step 3 — optional crop context.
  const [cropType, setCropType] = useState('');
  const [plantingDate, setPlantingDate] = useState('');
  const [irrigationType, setIrrigationType] = useState('');

  // Backend-derived season identity. The farmer does not edit this.
  const [seasonId, setSeasonId] = useState<string | null>(null);

  // True only when the farmer has changed the crop/season form
  // since the saved farm was loaded or last synchronized.
  const [
    cropContextDirty,
    setCropContextDirty,
  ] = useState(false);


  // ── Authentication state ─────────────────────────────────────

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(
      auth,
      (user) => {
        setCurrentUser(user);
        setAuthLoading(false);

        if (!user) {
          setSavedFarms([]);
          setActiveFarmId(null);
          setTrend(null);
        }
      }
    );

    return () => unsubscribe();
  }, []);


  // Restore a pending farm after the user signs in/signs up.
  useEffect(() => {
    if (!currentUser) return;

    const params = new URLSearchParams(window.location.search);
    const shouldContinueSave = params.get('continueSave') === '1';

    if (!shouldContinueSave) return;

    const savedDraft = sessionStorage.getItem(
      'tagintell_pending_farm_draft'
    );

    if (!savedDraft) return;

    try {
      const parsed = JSON.parse(savedDraft);

      if (parsed.coordinates && parsed.results) {
        setCoordinates(parsed.coordinates);
        setResults(parsed.results);
        setTrend(null);
        setError(null);
        setActiveFarmId(null);
        setLoadFarmTrigger(parsed.coordinates);

        const restoredCropType =
          parsed.cropType ??
          parsed.results?.crop_type ??
          parsed.results?.crop_context?.crop_type ??
          '';

        const restoredPlantingDate =
          parsed.plantingDate ??
          parsed.results?.planting_date ??
          parsed.results?.crop_context?.planting_date ??
          '';

        const restoredIrrigationType =
          parsed.irrigationType ??
          parsed.results?.irrigation_type ??
          parsed.results?.crop_context?.irrigation_type ??
          '';

        const restoredSeasonId =
          parsed.seasonId ??
          parsed.results?.season_id ??
          parsed.results?.crop_context?.season_id ??
          null;

        setCropType(restoredCropType || '');
        setPlantingDate(restoredPlantingDate || '');
        setIrrigationType(restoredIrrigationType || '');
        setSeasonId(restoredSeasonId || null);
        setCropContextDirty(false);

        setShowSaveModal(true);
      }

      sessionStorage.removeItem('tagintell_pending_farm_draft');
      window.history.replaceState({}, '', '/');
    } catch {
      sessionStorage.removeItem('tagintell_pending_farm_draft');
    }
  }, [currentUser]);


  // ── Animated loading steps ───────────────────────────────────

  useEffect(() => {
    if (!loading) {
      setLoadingStep(0);
      return;
    }

    const interval = setInterval(() => {
      setLoadingStep((prev) =>
        Math.min(prev + 1, LOADING_STEPS.length - 1)
      );
    }, 3000);

    return () => clearInterval(interval);
  }, [loading]);


  // ── Authentication helpers ──────────────────────────────────

  const getFarmAuthHeaders = async () => {
    if (!currentUser) {
      throw new Error('Login required');
    }

    const token = await currentUser.getIdToken();

    return {
      Authorization: `Bearer ${token}`,
      'x-user-id': currentUser.uid,
    };
  };


  const savePendingFarmDraft = () => {
    if (!coordinates || !results) return;

    sessionStorage.setItem(
      'tagintell_pending_farm_draft',
      JSON.stringify({
        coordinates,
        results,
        cropType,
        plantingDate,
        irrigationType,
        seasonId,
        savedAt: new Date().toISOString(),
      })
    );
  };


  // ── Crop-context helpers ─────────────────────────────────────

  const invalidateAnalysisAfterCropEdit = () => {
    // A report belongs to the crop inputs that produced it. If the farmer
    // changes those inputs, clear the old report so it cannot later be
    // saved under different crop information.
    setResults(null);
    setTrend(null);
    setError(null);
  };


  const handleCropTypeChange = (value: string) => {
    setCropType(value);

    // Crop changed, so the old season identity may no longer be valid.
    setSeasonId(null);

    // The saved farm's crop information now differs from what was loaded.
    setCropContextDirty(true);

    invalidateAnalysisAfterCropEdit();
  };


  const handlePlantingDateChange = (value: string) => {
    setPlantingDate(value);

    // Planting date is part of season identity.
    setSeasonId(null);

    setCropContextDirty(true);

    invalidateAnalysisAfterCropEdit();
  };


  const handleIrrigationTypeChange = (value: string) => {
    setIrrigationType(value);

    // Irrigation does not change season identity, but it does change
    // the saved farm's management context.
    setCropContextDirty(true);

    invalidateAnalysisAfterCropEdit();
  };


  const buildAnalysisPayload = (
    polygon: number[][],
    resolvedSeasonId: string | null = seasonId
  ): AnalysisPayload => {
    const payload: AnalysisPayload = {
      polygon,
    };

    const cleanCropType = cropType.trim();
    const cleanPlantingDate = plantingDate.trim();
    const cleanIrrigationType = irrigationType.trim();

    // Omit unsupplied keys instead of sending empty strings. This keeps a
    // polygon-only request structurally polygon-only all the way to the API.
    if (cleanCropType) {
      payload.crop_type = cleanCropType;
    }

    if (cleanPlantingDate) {
      payload.planting_date = cleanPlantingDate;
    }

    if (cleanIrrigationType) {
      payload.irrigation_type = cleanIrrigationType;
    }

    if (resolvedSeasonId) {
      payload.season_id = resolvedSeasonId;
    }

    return payload;
  };


  const syncActiveFarmSeason = async (): Promise<string | null> => {
    if (!activeFarmId || !currentUser) {
      return seasonId;
    }

    const headers = await getFarmAuthHeaders();

    const res = await axios.put(
      `${API_BASE_URL}/farms/${activeFarmId}/season`,
      {
        crop_type: cropType.trim() || null,
        planting_date: plantingDate.trim() || null,
        irrigation_type: irrigationType.trim() || null,
        season_id: seasonId,
      },
      { headers }
    );

    const resolvedSeasonId = res.data?.season_id || null;

    setSeasonId(resolvedSeasonId);

    // The database now matches what is currently in the form.
    setCropContextDirty(false);

    return resolvedSeasonId;
  };


  // ── Save analysis history ────────────────────────────────────

  // Used by both:
  // 1. Re-analysing an already-saved farm.
  // 2. Saving a farm for the first time, where the analysis just run
  //    becomes Analysis #1.
  const saveAnalysisForFarm = async (
    farmId: string,
    analysis: FarmAnalysisResponse
  ) => {
    if (!currentUser) return;

    const d = analysis;
    const t = d.technical_details || {};
    const r = d.recent_comparison || {};
    const i = d.image_info || {};
    const c = d.crop_context || {};
    const ct = c.crop_timing_context || {};

    const headers = await getFarmAuthHeaders();

    await axios.post(
      `${API_BASE_URL}/farms/analysis/save`,
      {
        farm_id: farmId,

        // Legacy database field.
        stress_type:
          t.stress_type ??
          d.stress_type,

        severity: d.severity,
        attention_area: d.attention_area,
        attention_source: t.attention_source,

        confidence:
          t.confidence !== undefined
            ? String(t.confidence)
            : undefined,

        title: d.title,
        summary: d.summary,
        action: d.action,
        recommendation: d.recommendation,
        hotspot_summary: d.hotspot_summary,

        ndvi: t.ndvi,

        // NDMI is now the authoritative moisture-condition field.
        // farms.py owns the temporary backward-compatibility write to
        // the old ndwi database column.
        ndmi:
          t.ndmi ??
          t.ndwi,

        ndre: t.ndre,
        savi: t.savi,
        gndvi: t.gndvi,

        // Save exactly what the backend used for this observation.
        // Do not recompute DAP/timing in the browser.
        crop_type:
          d.crop_type ??
          c.crop_type,

        planting_date:
          d.planting_date ??
          c.planting_date,

        irrigation_type:
          d.irrigation_type ??
          c.irrigation_type,

        season_id:
          d.season_id ??
          c.season_id,

        days_after_planting:
          d.days_after_planting ??
          c.days_after_planting,

        timing_phase:
          d.timing_phase ??
          ct.timing_phase,

        cover_screen_mode:
          d.cover_screen_mode ??
          c.cover_screen_mode ??
          ct.cover_screen_mode,

        decline_expected:
          d.decline_expected ??
          c.decline_expected ??
          ct.decline_expected,

        has_crop_context:
          d.has_crop_context ??
          c.has_crop_context,

        image_date: i.date,

        // Do NOT persist image_info.cloud_cover_percent into the legacy
        // cloud_cover column. That value is granule-wide metadata, not
        // this field's cloud cover.

        // TEMPORARY legacy save-schema fields. New GEE responses may
        // leave these undefined.
        search_window_start: i.search_window_start,
        search_window_end: i.search_window_end,
        selection_mode: i.selection_mode,
        candidate_count: i.candidate_count,
        clean_candidate_count: i.clean_candidate_count,

        // Legacy comparison fields remain until historical_service.py
        // replaces this old recent-composite path.
        recent_ndvi_composite: r.recent_ndvi_composite,
        recent_ndre_composite: r.recent_ndre_composite,
        recent_ndwi_composite:
          r.recent_ndmi_composite ??
          r.recent_ndwi_composite,
        recent_savi_composite: r.recent_savi_composite,
        recent_gndvi_composite: r.recent_gndvi_composite,

        ndvi_delta_recent: r.ndvi_delta_recent,
        ndre_delta_recent: r.ndre_delta_recent,
        ndwi_delta_recent:
          r.ndmi_delta_recent ??
          r.ndwi_delta_recent,
        savi_delta_recent: r.savi_delta_recent,
        gndvi_delta_recent: r.gndvi_delta_recent,

        recent_condition_status: r.recent_condition_status,
      },
      { headers }
    );
  };


  // ── Saved farms ──────────────────────────────────────────────

  const fetchFarms = async () => {
    if (!currentUser) {
      setShowAuthModal(true);
      return;
    }

    setFarmsLoading(true);

    try {
      const headers = await getFarmAuthHeaders();

      const res = await axios.get(
        `${API_BASE_URL}/farms`,
        { headers }
      );

      setSavedFarms(res.data.farms || []);
    } catch {
      setSavedFarms([]);
    } finally {
      setFarmsLoading(false);
    }
  };


  const fetchTrend = async (
    farmId: string
  ) => {
    if (!currentUser) {
      setTrend(null);
      return;
    }

    try {
      const headers = await getFarmAuthHeaders();

      const res = await axios.get(
        `${API_BASE_URL}/farms/${farmId}/trend`,
        { headers }
      );

      setTrend(res.data);
    } catch {
      setTrend(null);
    }
  };


  const handleSaveClick = () => {
    if (!coordinates) return;

    if (!currentUser) {
      savePendingFarmDraft();
      setShowAuthModal(true);
      return;
    }

    setShowSaveModal(true);
  };


  const handleMyFarmsClick = async () => {
    if (!currentUser) {
      setShowAuthModal(true);
      return;
    }

    await fetchFarms();
    setShowMyFarms(true);
  };


  const saveFarm = async (
    name: string
  ) => {
    if (!coordinates || !currentUser) return;

    try {
      const headers = await getFarmAuthHeaders();
      const c = results?.crop_context || {};

      const farmCropType =
        results?.crop_type ??
        c.crop_type ??
        (cropType.trim() || undefined);

      const farmPlantingDate =
        results?.planting_date ??
        c.planting_date ??
        (plantingDate.trim() || undefined);

      const farmIrrigationType =
        results?.irrigation_type ??
        c.irrigation_type ??
        (irrigationType.trim() || undefined);

      const farmSeasonId =
        results?.season_id ??
        c.season_id ??
        seasonId ??
        undefined;

      const res = await axios.post(
        `${API_BASE_URL}/farms`,
        {
          name,
          polygon: coordinates,

          area_ha:
            results?.farm_area?.hectares,

          area_acres:
            results?.farm_area?.acres,

          crop_type: farmCropType,
          planting_date: farmPlantingDate,
          irrigation_type: farmIrrigationType,
          season_id: farmSeasonId,
        },
        { headers }
      );

      const farmId = res.data.id;

      setActiveFarmId(farmId);
      setSeasonId(res.data.season_id || farmSeasonId || null);
      setCropContextDirty(false);

      setSaveSuccess(`"${res.data.name}" saved successfully`);
      setShowSaveModal(false);

      setTimeout(() => setSaveSuccess(null), 3000);

      // The analysis the user just ran becomes Analysis #1.
      if (
        results &&
        results.status !== 'failed' &&
        !results.error
      ) {
        try {
          await saveAnalysisForFarm(
            farmId,
            results
          );
        } catch {
          // Farm itself saved successfully.
          // Failed history write should not turn into a failed farm save.
        }
      }

      fetchFarms();
      await fetchTrend(farmId);
    } catch (err: any) {
      alert(
        err.response?.data?.detail ||
        'Failed to save farm.'
      );
    }
  };


  const loadFarm = async (
    farm: SavedFarm
  ) => {
    if (!currentUser) {
      setShowAuthModal(true);
      return;
    }

    try {
      const headers = await getFarmAuthHeaders();

      const res = await axios.get(
        `${API_BASE_URL}/farms/${farm.id}`,
        { headers }
      );

      const polygon = res.data.polygon;

      setActiveFarmId(farm.id);
      setLoadFarmTrigger(polygon);
      setCoordinates(polygon);

      setCropType(res.data.crop_type || '');
      setPlantingDate(res.data.planting_date || '');
      setIrrigationType(res.data.irrigation_type || '');
      setSeasonId(res.data.season_id || null);
      setCropContextDirty(false);

      setResults(null);
      setTrend(null);
      setError(null);
      setShowMyFarms(false);

      await fetchTrend(farm.id);
    } catch {
      alert('Failed to load farm.');
    }
  };


  const deleteFarm = async (
    id: string
  ) => {
    if (!currentUser) {
      setShowAuthModal(true);
      return;
    }

    if (!confirm('Delete this farm?')) return;

    try {
      const headers = await getFarmAuthHeaders();

      await axios.delete(
        `${API_BASE_URL}/farms/${id}`,
        { headers }
      );

      setSavedFarms((prev) =>
        prev.filter((f) => f.id !== id)
      );

      if (activeFarmId === id) {
        setActiveFarmId(null);
        setTrend(null);
        setSeasonId(null);
      }
    } catch {
      alert('Failed to delete farm.');
    }
  };


  const handleLogout = async () => {
    await signOut(auth);

    setSaveSuccess('Logged out successfully');
    setTimeout(() => setSaveSuccess(null), 2500);
  };


  // ── Polygon events ───────────────────────────────────────────

  const handlePolygonComplete = (
    coords: number[][]
  ) => {
    setCoordinates(coords);
    setResults(null);
    setTrend(null);
    setError(null);
    setActiveFarmId(null);
    setSeasonId(null);
    setCropContextDirty(false);
  };


  const handlePolygonClear = () => {
    setCoordinates(null);
    setResults(null);
    setTrend(null);
    setError(null);
    setActiveFarmId(null);
    setSeasonId(null);
    setCropContextDirty(false);

    // Clearing the boundary starts a fresh unsaved farm context too.
    setCropType('');
    setPlantingDate('');
    setIrrigationType('');
  };


  // ── Run Farm Watch analysis ─────────────────────────────────

  const analyzeFarm = async () => {
    // Matches intake_agent: open ring with 3 corners is accepted and
    // closed server-side.
    if (!coordinates || coordinates.length < 3) {
      alert('Please draw your farm boundary first');
      return;
    }

    setLoading(true);
    setError(null);
    setResults(null);
    setTrend(null);
    setLoadingStep(0);

    try {
      // A saved farm has a persistent CURRENT crop/season record.
      //
      // Only synchronize when the farmer actually changed the crop form.
      // An untouched saved farm does not need another database update.
      //
      // This update is deliberately isolated from satellite analysis.
      // If the farm-record update fails, Farm Watch must still be allowed
      // to analyze the boundary.
      let resolvedSeasonId = seasonId;

      if (
        activeFarmId &&
        currentUser &&
        cropContextDirty
      ) {
        try {
          resolvedSeasonId =
            await syncActiveFarmSeason();
        } catch {
          // Keep whatever season identity is currently available and
          // continue with the satellite analysis.
          //
          // cropContextDirty remains true, so a later attempt can try
          // synchronizing the farm record again.
          resolvedSeasonId = seasonId;
        }
      }

      const analysisPayload = buildAnalysisPayload(
        coordinates,
        resolvedSeasonId
      );

      const response = await axios.post<FarmAnalysisResponse>(
        `${API_BASE_URL}/analyze/agent`,
        analysisPayload
      );

      // The backend returns structured analysis failures with HTTP 200.
      // Do not convert them into page-level network errors.
      if (
        response.data?.error ||
        response.data?.status === 'failed'
      ) {
        setResults(response.data);
        setError(null);
        return;
      }

      // Successful analysis.
      setResults(response.data);

      const responseSeasonId =
        response.data.season_id ??
        response.data.crop_context?.season_id ??
        resolvedSeasonId ??
        null;

      setSeasonId(responseSeasonId);

      // If this is an already-saved farm, automatically save the new
      // successful analysis to history.
      if (
        activeFarmId &&
        response.data &&
        currentUser
      ) {
        try {
          await saveAnalysisForFarm(
            activeFarmId,
            response.data
          );

          await fetchTrend(activeFarmId);
        } catch {
          setTrend(null);
        }
      }
    } catch (err: any) {
      const message =
        typeof err.response?.data?.detail === 'string'
          ? err.response.data.detail
          : err.response?.data?.detail
            ? JSON.stringify(err.response.data.detail)
            : 'Failed to analyze farm. Please try again.';

      setError(message);
    } finally {
      setLoading(false);
    }
  };


  // ── Render ──────────────────────────────────────────────────

  return (
    <div
      style={{
        minHeight: '100vh',
        background:
          'linear-gradient(135deg, #03081a 0%, #060d24 50%, #040a1a 100%)',
        color: 'white',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        position: 'relative',
      }}
    >
      <SatelliteBackground />


      {showAuthModal && (
        <AuthRequiredModal
          onClose={() => setShowAuthModal(false)}
        />
      )}


      {showSaveModal && (
        <SaveFarmModal
          defaultName={`My Farm ${savedFarms.length + 1}`}
          onSave={saveFarm}
          onClose={() => setShowSaveModal(false)}
        />
      )}


      {showMyFarms && (
        <MyFarmsPanel
          farms={savedFarms}
          loading={farmsLoading}
          onSelect={loadFarm}
          onDelete={deleteFarm}
          onClose={() => setShowMyFarms(false)}
        />
      )}


      {/* ── Header ───────────────────────────────────────────── */}

      <header
        style={{
          position: 'relative',
          zIndex: 10,
          borderBottom: '1px solid rgba(34,214,122,0.15)',
          background: 'rgba(3,8,26,0.8)',
          backdropFilter: 'blur(20px)',
        }}
      >
        <div
          style={{
            maxWidth: '1280px',
            margin: '0 auto',
            padding: '16px 20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '14px',
            }}
          >
            <div
              style={{
                width: '44px',
                height: '44px',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, #22d67a20, #22d67a40)',
                border: '1px solid #22d67a50',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '22px',
              }}
            >
              🛰️
            </div>

            <div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: '8px',
                }}
              >
                <span
                  style={{
                    fontSize: '22px',
                    fontWeight: '800',
                    letterSpacing: '-0.5px',
                    color: 'white',
                  }}
                >
                  Tagintell
                </span>

                <span
                  style={{
                    fontSize: '18px',
                    fontWeight: '600',
                    color: '#22d67a',
                  }}
                >
                  Farm Watch
                </span>
              </div>

              <div
                style={{
                  fontSize: '11px',
                  color: 'rgba(255,255,255,0.4)',
                  letterSpacing: '1.5px',
                  textTransform: 'uppercase',
                  marginTop: '2px',
                }}
              >
                AI-Powered Satellite Intelligence for farms and forests
              </div>
            </div>
          </div>


          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              flexWrap: 'wrap',
            }}
          >
            {!authLoading && currentUser && (
              <div
                style={{
                  fontSize: '12px',
                  color: 'rgba(255,255,255,0.55)',
                  maxWidth: '180px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {currentUser.email}
              </div>
            )}


            {!authLoading && !currentUser && (
              <>
                <Link
                  href="/login"
                  style={{
                    padding: '8px 14px',
                    borderRadius: '20px',
                    border: '1px solid rgba(255,255,255,0.15)',
                    background: 'rgba(255,255,255,0.05)',
                    color: 'rgba(255,255,255,0.75)',
                    textDecoration: 'none',
                    fontSize: '13px',
                    fontWeight: 600,
                  }}
                >
                  Log in
                </Link>

                <Link
                  href="/signup"
                  style={{
                    padding: '8px 14px',
                    borderRadius: '20px',
                    border: '1px solid rgba(34,214,122,0.25)',
                    background: 'rgba(34,214,122,0.12)',
                    color: '#22d67a',
                    textDecoration: 'none',
                    fontSize: '13px',
                    fontWeight: 700,
                  }}
                >
                  Create account
                </Link>
              </>
            )}


            {currentUser && (
              <button
                onClick={handleLogout}
                style={{
                  padding: '8px 14px',
                  borderRadius: '20px',
                  border: '1px solid rgba(255,255,255,0.12)',
                  background: 'rgba(255,255,255,0.04)',
                  color: 'rgba(255,255,255,0.6)',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                Log out
              </button>
            )}


            <button
              onClick={handleMyFarmsClick}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                borderRadius: '20px',
                border: '1px solid rgba(255,255,255,0.15)',
                background: 'rgba(255,255,255,0.05)',
                color: 'rgba(255,255,255,0.7)',
                cursor: 'pointer',
                fontSize: '13px',
              }}
            >
              🌾 My Farms{' '}

              {savedFarms.length > 0 && (
                <span
                  style={{
                    background: '#22d67a',
                    color: '#03081a',
                    borderRadius: '10px',
                    padding: '1px 6px',
                    fontSize: '10px',
                    fontWeight: '700',
                  }}
                >
                  {savedFarms.length}
                </span>
              )}
            </button>


            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                background: 'rgba(34,214,122,0.1)',
                border: '1px solid rgba(34,214,122,0.2)',
                borderRadius: '20px',
                padding: '6px 14px',
                fontSize: '12px',
                color: '#22d67a',
              }}
            >
              <span
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  background: '#22d67a',
                  display: 'inline-block',
                }}
              />

              Sentinel-2 Imagery
            </div>
          </div>
        </div>
      </header>


      {/* ── Main content ─────────────────────────────────────── */}

      <main
        style={{
          position: 'relative',
          zIndex: 10,
          maxWidth: '1280px',
          margin: '0 auto',
          padding: '24px 16px',
        }}
      >
        <div
          style={{
            textAlign: 'center',
            marginBottom: '32px',
          }}
        >
          <h1
            style={{
              fontSize: 'clamp(24px, 5vw, 42px)',
              fontWeight: '800',
              margin: '0 0 8px',
              lineHeight: 1.2,
            }}
          >
            AI-powered Satellite Intelligence for{' '}

            <span style={{ color: '#22d67a' }}>
              Your Farm
            </span>
          </h1>

          <p
            style={{
              color: 'rgba(255,255,255,0.5)',
              fontSize: '15px',
              margin: 0,
            }}
          >
            Draw your farm boundary, monitor crop condition, and identify
            areas that may need attention.
          </p>
        </div>


        {/* ── Save success notification ─────────────────────── */}

        {saveSuccess && (
          <div
            style={{
              position: 'fixed',
              bottom: '24px',
              left: '50%',
              transform: 'translateX(-50%)',
              background: '#22d67a',
              color: '#03081a',
              padding: '12px 20px',
              borderRadius: '12px',
              fontWeight: '700',
              fontSize: '13px',
              zIndex: 200,
              boxShadow: '0 4px 20px rgba(34,214,122,0.4)',
            }}
          >
            ✓ {saveSuccess}
          </div>
        )}


        {/* ── Saved farm indicator ──────────────────────────── */}

        {activeFarmId && currentUser && (
          <div
            style={{
              marginBottom: '16px',
              padding: '10px 16px',
              background: 'rgba(34,214,122,0.08)',
              border: '1px solid rgba(34,214,122,0.2)',
              borderRadius: '10px',
              fontSize: '12px',
              color: '#22d67a',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <span>📍</span>

            <span>
              Saved farm loaded — analysis history will be recorded
              automatically
            </span>
          </div>
        )}


        {/* ── Main map / results grid ───────────────────────── */}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns:
              results || loading
                ? '1fr 1fr'
                : '1fr',
            gap: '20px',
            alignItems: 'start',
          }}
          className="main-grid"
        >
          {/* LEFT: map and controls */}

          <div>
            <div
              style={{
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: '16px',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  padding: '14px 18px',
                  borderBottom: '1px solid rgba(255,255,255,0.06)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                  }}
                >
                  <span
                    style={{
                      width: '24px',
                      height: '24px',
                      borderRadius: '6px',
                      background: 'rgba(34,214,122,0.15)',
                      border: '1px solid rgba(34,214,122,0.3)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '13px',
                    }}
                  >
                    1
                  </span>

                  <span
                    style={{
                      fontWeight: '600',
                      fontSize: '14px',
                    }}
                  >
                    Define Farm Boundary
                  </span>
                </div>


                {coordinates && (
                  <span
                    style={{
                      fontSize: '11px',
                      color: '#22d67a',
                      background: 'rgba(34,214,122,0.1)',
                      border: '1px solid rgba(34,214,122,0.2)',
                      padding: '3px 10px',
                      borderRadius: '10px',
                    }}
                  >
                    ✓ Boundary ready
                  </span>
                )}
              </div>


              <div
                style={{
                  height: 'clamp(350px, 50vw, 500px)',
                }}
              >
                <Map
                  onPolygonComplete={handlePolygonComplete}
                  onPolygonClear={handlePolygonClear}
                  loadPolygon={loadFarmTrigger}
                  onPolygonLoaded={() => setLoadFarmTrigger(null)}
                />
              </div>
            </div>


            {coordinates && (
              <CropContextForm
                cropType={cropType}
                plantingDate={plantingDate}
                irrigationType={irrigationType}
                onCropTypeChange={handleCropTypeChange}
                onPlantingDateChange={handlePlantingDateChange}
                onIrrigationTypeChange={handleIrrigationTypeChange}
              />
            )}


            <div
              style={{
                marginTop: '14px',
                display: 'flex',
                gap: '10px',
              }}
            >
              <button
                onClick={analyzeFarm}
                disabled={
                  loading ||
                  !coordinates
                }
                style={{
                  flex: 1,
                  padding: '16px',
                  borderRadius: '12px',
                  border: 'none',
                  cursor:
                    loading || !coordinates
                      ? 'not-allowed'
                      : 'pointer',
                  fontSize: '16px',
                  fontWeight: '700',
                  letterSpacing: '0.5px',
                  transition: 'all 0.2s ease',
                  background:
                    loading
                      ? 'rgba(255,255,255,0.05)'
                      : !coordinates
                        ? 'rgba(255,255,255,0.05)'
                        : 'linear-gradient(135deg, #22d67a, #16a85c)',
                  color:
                    loading || !coordinates
                      ? 'rgba(255,255,255,0.3)'
                      : '#03081a',
                  boxShadow:
                    loading || !coordinates
                      ? 'none'
                      : '0 4px 20px rgba(34,214,122,0.3)',
                }}
              >
                {loading
                  ? '🔄 Analyzing...'
                  : !coordinates
                    ? '👆 Draw boundary to begin'
                    : '📡 Analyze My Farm'}
              </button>
            </div>


            {/* Page-level errors are reserved for HTTP/network failures. */}

            {error && (
              <div
                style={{
                  marginTop: '12px',
                  padding: '14px 16px',
                  background: 'rgba(239,68,68,0.1)',
                  border: '1px solid rgba(239,68,68,0.3)',
                  borderRadius: '12px',
                  fontSize: '13px',
                  color: '#fca5a5',
                }}
              >
                ❌ {error}
              </div>
            )}
          </div>


          {/* RIGHT: loader / results */}

          {(loading || results) && (
            <div>
              {loading ? (
                <div
                  style={{
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: '16px',
                  }}
                >
                  <div
                    style={{
                      padding: '14px 18px',
                      borderBottom: '1px solid rgba(255,255,255,0.06)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                    }}
                  >
                    <span
                      style={{
                        width: '24px',
                        height: '24px',
                        borderRadius: '6px',
                        background: 'rgba(34,214,122,0.15)',
                        border: '1px solid rgba(34,214,122,0.3)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '13px',
                      }}
                    >
                      2
                    </span>

                    <span
                      style={{
                        fontWeight: '600',
                        fontSize: '14px',
                      }}
                    >
                      Fetching and analyzing your farm data...
                    </span>
                  </div>

                  <SatelliteLoader step={loadingStep} />
                </div>
              ) : results ? (
                <div>
                  <div
                    style={{
                      padding: '0 0 14px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                    }}
                  >
                    <span
                      style={{
                        width: '24px',
                        height: '24px',
                        borderRadius: '6px',
                        background: 'rgba(34,214,122,0.15)',
                        border: '1px solid rgba(34,214,122,0.3)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '13px',
                      }}
                    >
                      2
                    </span>

                    <span
                      style={{
                        fontWeight: '600',
                        fontSize: '14px',
                      }}
                    >
                      Farm Analysis Report
                    </span>
                  </div>


                  {/* Save Farm is shown only for a successful analysis. */}

                  {!activeFarmId &&
                    results.status !== 'failed' &&
                    !results.error && (
                      <div
                        style={{
                          marginBottom: '14px',
                          padding: '14px 16px',
                          background: 'rgba(250,204,21,0.08)',
                          border: '1px solid rgba(250,204,21,0.2)',
                          borderRadius: '12px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '12px',
                          flexWrap: 'wrap',
                        }}
                      >
                        <div
                          style={{
                            fontSize: '13px',
                            color: '#facc15',
                            lineHeight: 1.5,
                            flex: 1,
                            minWidth: '220px',
                          }}
                        >
                          {currentUser
                            ? '⚠️ This analysis is temporary. Save this farm to track changes over time.'
                            : '⚠️ This analysis is temporary. Create an account or log in to save this farm and track changes over time.'}
                        </div>

                        <button
                          onClick={handleSaveClick}
                          style={{
                            padding: '10px 14px',
                            borderRadius: '10px',
                            border: '1px solid rgba(34,214,122,0.35)',
                            background: 'linear-gradient(135deg, #22d67a, #16a85c)',
                            color: '#03081a',
                            cursor: 'pointer',
                            fontSize: '13px',
                            fontWeight: 800,
                            whiteSpace: 'nowrap',
                          }}
                        >
                          💾 Save Farm
                        </button>
                      </div>
                    )}


                  <Results
                    data={results}
                    polygon={coordinates}
                    trend={trend}
                  />
                </div>
              ) : null}
            </div>
          )}
        </div>


        {/* Empty state */}

        {!loading && !results && (
          <div
            style={{
              marginTop: '40px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '16px',
              color: 'rgba(255,255,255,0.2)',
            }}
          >
            <div
              style={{
                fontSize: '48px',
                opacity: 0.3,
              }}
            >
              🌾
            </div>

            <p
              style={{
                fontSize: '14px',
                margin: 0,
              }}
            >
              Draw your farm boundary above to begin analysis
            </p>
          </div>
        )}
      </main>


      {/* ── Footer ───────────────────────────────────────────── */}

      <footer
        style={{
          position: 'relative',
          zIndex: 10,
          borderTop: '1px solid rgba(255,255,255,0.05)',
          padding: '16px',
          textAlign: 'center',
          color: 'rgba(255,255,255,0.2)',
          fontSize: '12px',
          marginTop: '40px',
        }}
      >
        Tagintell Platform © 2026 — AI-Powered Satellite Intelligence

        <br />

        <span
          style={{
            fontSize: '10px',
            opacity: 0.6,
          }}
        >
          Built by Timothy Okoliko
        </span>
      </footer>


      <style>{`
        @media (max-width: 900px) {
          .crop-context-grid {
            grid-template-columns: 1fr !important;
          }
        }

        @media (max-width: 768px) {
          .main-grid {
            grid-template-columns: 1fr !important;
          }
        }

        @keyframes signalPulse {
          0%, 100% {
            opacity: 1;
            transform: scale(1);
          }

          50% {
            opacity: 0.4;
            transform: scale(1.3);
          }
        }
      `}</style>
    </div>
  );
}
