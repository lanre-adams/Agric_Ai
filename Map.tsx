'use client';

import { useEffect, useRef, useState } from 'react';

interface MapProps {
  onPolygonComplete: (coords: number[][]) => void;
  onPolygonClear: () => void;
  loadPolygon?: number[][] | null;
  onPolygonLoaded?: () => void;
}

type InputMode = 'draw' | 'latlng' | 'search';
type MapStyle = 'satellite' | 'streets' | 'hybrid';

export default function Map({
  onPolygonComplete,
  onPolygonClear,
  loadPolygon,
  onPolygonLoaded,
}: MapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const searchMarkerRef = useRef<any>(null);
  const [mode, setMode] = useState<InputMode>('draw');
  const [mapStyle, setMapStyle] = useState<MapStyle>('hybrid');
  const [points, setPoints] = useState<[number, number][]>([]);
  const [isComplete, setIsComplete] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [latInput, setLatInput] = useState('');
  const [lngInput, setLngInput] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [mapLoaded, setMapLoaded] = useState(false);
  const pointsRef = useRef<[number, number][]>([]);
  const isCompleteRef = useRef(false);
  const modeRef = useRef<InputMode>('draw');

  const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || '';

  const STYLE_URLS: Record<MapStyle, string> = {
    satellite: 'mapbox://styles/mapbox/satellite-v9',
    streets:   'mapbox://styles/mapbox/streets-v12',
    hybrid:    'mapbox://styles/mapbox/satellite-streets-v12',
  };

  // Load Mapbox CSS
  useEffect(() => {
    if (!document.getElementById('mapbox-css')) {
      const link = document.createElement('link');
      link.id = 'mapbox-css';
      link.rel = 'stylesheet';
      link.href = 'https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.css';
      document.head.appendChild(link);
    }

    // Inject popup styles
    if (!document.getElementById('mapbox-popup-styles')) {
      const style = document.createElement('style');
      style.id = 'mapbox-popup-styles';
      style.textContent = `
        .mapboxgl-popup-content {
          background: white !important;
          border-radius: 10px !important;
          padding: 12px 16px !important;
          box-shadow: 0 4px 20px rgba(0,0,0,0.25) !important;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        .mapboxgl-popup-tip {
          border-top-color: white !important;
        }
        .mapboxgl-popup-close-button {
          font-size: 16px;
          color: #64748b;
          padding: 4px 8px;
        }
      `;
      document.head.appendChild(style);
    }
  }, []);

  // Initialize Mapbox map
  useEffect(() => {
    if (!containerRef.current || !MAPBOX_TOKEN) return;

    let map: any;

    const initMap = async () => {
      const mapboxgl = (await import('mapbox-gl')).default;
      mapboxgl.accessToken = MAPBOX_TOKEN;

      map = new mapboxgl.Map({
        container: containerRef.current!,
        style: STYLE_URLS['hybrid'],
        center: [0, 20],
        zoom: 2,
        attributionControl: false,
      });

      map.addControl(
        new mapboxgl.NavigationControl({ showCompass: false }),
        'top-right'
      );

      const geolocate = new mapboxgl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: true,
        showAccuracyCircle: true,
      });
      map.addControl(geolocate, 'top-right');

      map.on('load', () => {
        setMapLoaded(true);

        setTimeout(() => {
          try { geolocate.trigger(); } catch {}
        }, 1000);

        map.addSource('polygon-points', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
        });
        map.addSource('polygon-line', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
        });
        map.addSource('polygon-fill', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
        });

        map.addLayer({
          id: 'polygon-fill',
          type: 'fill',
          source: 'polygon-fill',
          paint: { 'fill-color': '#22d67a', 'fill-opacity': 0.15 },
        });
        map.addLayer({
          id: 'polygon-line',
          type: 'line',
          source: 'polygon-line',
          paint: {
            'line-color': '#22d67a',
            'line-width': 2.5,
            'line-dasharray': [2, 1],
          },
        });
        map.addLayer({
          id: 'polygon-points',
          type: 'circle',
          source: 'polygon-points',
          paint: {
            'circle-radius': 6,
            'circle-color': '#22d67a',
            'circle-stroke-color': 'white',
            'circle-stroke-width': 2,
          },
        });
      });

      // Only draw when in draw mode
      map.on('click', (e: any) => {
        if (isCompleteRef.current) return;
        if (modeRef.current !== 'draw') return;
        const { lng, lat } = e.lngLat;
        const newPoint: [number, number] = [lng, lat];
        const newPoints = [...pointsRef.current, newPoint];
        pointsRef.current = newPoints;
        setPoints([...newPoints]);
        updateDrawing(map, newPoints, false);
      });

      map.on('dblclick', (e: any) => {
        e.preventDefault();
        if (modeRef.current !== 'draw') return;
        if (pointsRef.current.length < 3) return;
        closePolygon(map);
      });

      map.getCanvas().style.cursor = 'crosshair';
      mapRef.current = map;
    };

    initMap();
    return () => { if (map) map.remove(); };
  }, [MAPBOX_TOKEN]);

  // Keep refs in sync
  useEffect(() => { pointsRef.current = points; }, [points]);
  useEffect(() => { isCompleteRef.current = isComplete; }, [isComplete]);
  useEffect(() => {
    modeRef.current = mode;
    if (!mapRef.current) return;
    mapRef.current.getCanvas().style.cursor = mode === 'draw' ? 'crosshair' : 'grab';
  }, [mode]);

  // Switch map style without losing drawings
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return;
    const currentPoints = pointsRef.current;
    const currentComplete = isCompleteRef.current;

    mapRef.current.setStyle(STYLE_URLS[mapStyle]);

    mapRef.current.once('style.load', () => {
      mapRef.current.addSource('polygon-points', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      mapRef.current.addSource('polygon-line', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      mapRef.current.addSource('polygon-fill', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      mapRef.current.addLayer({
        id: 'polygon-fill',
        type: 'fill',
        source: 'polygon-fill',
        paint: { 'fill-color': '#22d67a', 'fill-opacity': 0.15 },
      });
      mapRef.current.addLayer({
        id: 'polygon-line',
        type: 'line',
        source: 'polygon-line',
        paint: {
          'line-color': '#22d67a',
          'line-width': 2.5,
          'line-dasharray': [2, 1],
        },
      });
      mapRef.current.addLayer({
        id: 'polygon-points',
        type: 'circle',
        source: 'polygon-points',
        paint: {
          'circle-radius': 6,
          'circle-color': '#22d67a',
          'circle-stroke-color': 'white',
          'circle-stroke-width': 2,
        },
      });

      if (currentPoints.length > 0) {
        updateDrawing(mapRef.current, currentPoints, currentComplete);
      }
    });
  }, [mapStyle]);

  // Load a saved farm polygon
  useEffect(() => {
    if (!loadPolygon || !mapRef.current || !mapLoaded) return;

    const pts = loadPolygon as [number, number][];
    const openPts =
      pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1]
        ? pts.slice(0, -1)
        : pts;

    pointsRef.current = openPts;
    isCompleteRef.current = true;
    setPoints(openPts);
    setIsComplete(true);
    updateDrawing(mapRef.current, openPts, true);

    const lngs = openPts.map(p => p[0]);
    const lats = openPts.map(p => p[1]);
    mapRef.current.fitBounds(
      [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
      { padding: 60, duration: 1200 }
    );

    if (onPolygonLoaded) onPolygonLoaded();
  }, [loadPolygon, mapLoaded]);

  function updateDrawing(map: any, pts: [number, number][], complete: boolean) {
    if (!map.getSource('polygon-points')) return;

    map.getSource('polygon-points').setData({
      type: 'FeatureCollection',
      features: pts.map(p => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: p },
        properties: {},
      })),
    });

    if (pts.length >= 2) {
      const lineCoords = complete ? [...pts, pts[0]] : pts;
      map.getSource('polygon-line').setData({
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: lineCoords },
          properties: {},
        }],
      });
    }

    if (complete && pts.length >= 3) {
      map.getSource('polygon-fill').setData({
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [[...pts, pts[0]]] },
          properties: {},
        }],
      });
    }
  }

  function closePolygon(map: any) {
    const pts = pointsRef.current;
    if (pts.length < 3) return;
    updateDrawing(map, pts, true);
    setIsComplete(true);
    onPolygonComplete([...pts, pts[0]]);
  }

  function clearAll() {
    pointsRef.current = [];
    isCompleteRef.current = false;
    setPoints([]);
    setIsComplete(false);
    onPolygonClear();

    if (mapRef.current && mapRef.current.getSource('polygon-points')) {
      const empty = { type: 'FeatureCollection', features: [] };
      mapRef.current.getSource('polygon-points').setData(empty);
      mapRef.current.getSource('polygon-line').setData(empty);
      mapRef.current.getSource('polygon-fill').setData(empty);
    }

    if (searchMarkerRef.current) {
      searchMarkerRef.current.remove();
      searchMarkerRef.current = null;
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim() || !MAPBOX_TOKEN) return;
    setSearchLoading(true);
    try {
      const res = await fetch(
        `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(searchQuery)}.json?access_token=${MAPBOX_TOKEN}&limit=5&types=place,address,region,locality,neighborhood,poi`
      );
      const data = await res.json();
      setSearchResults(data.features || []);
    } catch {
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  }

  function flyToResult(feature: any) {
    if (!mapRef.current) return;
    const [lng, lat] = feature.center;

    // Remove previous search marker
    if (searchMarkerRef.current) {
      searchMarkerRef.current.remove();
      searchMarkerRef.current = null;
    }

    import('mapbox-gl').then(({ default: mapboxgl }) => {
      // Red pin marker element
      const el = document.createElement('div');
      el.style.cssText = `
        width: 22px;
        height: 22px;
        background: #ef4444;
        border: 3px solid white;
        border-radius: 50% 50% 50% 0;
        transform: rotate(-45deg);
        box-shadow: 0 2px 8px rgba(0,0,0,0.4);
        cursor: pointer;
      `;

      const marker = new mapboxgl.Marker({ element: el, anchor: 'bottom' })
        .setLngLat([lng, lat])
        .setPopup(
          new mapboxgl.Popup({ offset: 25, closeButton: true })
            .setHTML(`
              <div style="font-size:13px; font-weight:600; color:#1e293b; max-width:220px; line-height:1.5;">
                📍 ${feature.place_name}
              </div>
            `)
        )
        .addTo(mapRef.current);

      marker.togglePopup();
      searchMarkerRef.current = marker;
    });

    mapRef.current.flyTo({ center: [lng, lat], zoom: 15, duration: 1500 });
    setSearchResults([]);
    setSearchQuery(feature.place_name?.split(',')[0] || searchQuery);
  }

  function handleLatLng(e: React.FormEvent) {
    e.preventDefault();
    const lat = parseFloat(latInput);
    const lng = parseFloat(lngInput);
    if (isNaN(lat) || isNaN(lng)) return;
    if (!mapRef.current) return;
    mapRef.current.flyTo({ center: [lng, lat], zoom: 16, duration: 1500 });
  }

  const tabStyle = (active: boolean) => ({
    padding: '8px 14px',
    borderRadius: '8px',
    border: 'none',
    cursor: 'pointer',
    fontSize: '12px',
    fontWeight: active ? '600' : '400',
    background: active ? 'rgba(34,214,122,0.15)' : 'transparent',
    color: active ? '#22d67a' : 'rgba(255,255,255,0.5)',
    transition: 'all 0.2s',
    outline: active ? '1px solid rgba(34,214,122,0.3)' : 'none',
  });

  const styleTabStyle = (active: boolean) => ({
    padding: '5px 10px',
    borderRadius: '6px',
    border: 'none',
    cursor: 'pointer',
    fontSize: '11px',
    fontWeight: active ? '700' : '400',
    background: active ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.05)',
    color: active ? 'white' : 'rgba(255,255,255,0.45)',
    transition: 'all 0.2s',
  });

  const inputStyle = {
    background: 'rgba(255,255,255,0.08)',
    border: '1px solid rgba(255,255,255,0.15)',
    borderRadius: '8px',
    padding: '8px 12px',
    color: 'white',
    fontSize: '13px',
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box' as const,
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: '#0d1a2e' }}>

      {/* Top controls */}
      <div style={{
        padding: '10px 12px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center',
        background: 'rgba(3,8,26,0.6)',
      }}>
        <button style={tabStyle(mode === 'draw')} onClick={() => setMode('draw')}>
          ✏️ Draw
        </button>
        <button style={tabStyle(mode === 'search')} onClick={() => setMode('search')}>
          🔍 Search
        </button>
        <button style={tabStyle(mode === 'latlng')} onClick={() => setMode('latlng')}>
          📍 Lat/Lng
        </button>

        {/* Style toggle */}
        <div style={{
          marginLeft: 'auto',
          display: 'flex', gap: '4px',
          background: 'rgba(255,255,255,0.06)',
          borderRadius: '8px', padding: '4px',
        }}>
          <button style={styleTabStyle(mapStyle === 'hybrid')} onClick={() => setMapStyle('hybrid')}>
            🛰 Hybrid
          </button>
          <button style={styleTabStyle(mapStyle === 'satellite')} onClick={() => setMapStyle('satellite')}>
            🌍 Satellite
          </button>
          <button style={styleTabStyle(mapStyle === 'streets')} onClick={() => setMapStyle('streets')}>
            🗺 Streets
          </button>
        </div>

        {(points.length > 0 || isComplete) && (
          <button
            onClick={clearAll}
            style={{
              padding: '8px 12px', borderRadius: '8px',
              border: '1px solid rgba(239,68,68,0.3)', cursor: 'pointer',
              fontSize: '12px', background: 'rgba(239,68,68,0.1)', color: '#fca5a5',
            }}
          >
            🗑 Clear
          </button>
        )}
      </div>

      {/* Search panel */}
      {mode === 'search' && (
        <div style={{ padding: '10px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'rgba(3,8,26,0.5)' }}>
          <form onSubmit={handleSearch} style={{ display: 'flex', gap: '8px' }}>
            <input
              style={{ ...inputStyle, flex: 1 }}
              placeholder="Search farm location or address..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
            <button type="submit" style={{
              padding: '8px 14px', borderRadius: '8px', border: 'none', cursor: 'pointer',
              background: 'rgba(34,214,122,0.2)', color: '#22d67a', fontSize: '13px',
              minWidth: '70px',
            }}>
              {searchLoading ? '...' : 'Search'}
            </button>
          </form>

          {searchResults.length > 0 && (
            <div style={{
              marginTop: '6px', maxHeight: '160px', overflowY: 'auto',
              background: 'rgba(3,8,26,0.95)', border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '8px',
            }}>
              {searchResults.map((r, i) => (
                <div
                  key={i}
                  onClick={() => flyToResult(r)}
                  style={{
                    padding: '10px 12px', cursor: 'pointer', fontSize: '12px',
                    color: 'rgba(255,255,255,0.8)',
                    borderBottom: i < searchResults.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(34,214,122,0.1)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  📍 {r.place_name}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Lat/Lng panel */}
      {mode === 'latlng' && (
        <div style={{ padding: '10px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'rgba(3,8,26,0.5)' }}>
          <form onSubmit={handleLatLng} style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <input
              style={{ ...inputStyle, flex: 1, minWidth: '100px' }}
              placeholder="Latitude (e.g. 6.52)"
              value={latInput}
              onChange={e => setLatInput(e.target.value)}
            />
            <input
              style={{ ...inputStyle, flex: 1, minWidth: '100px' }}
              placeholder="Longitude (e.g. 3.35)"
              value={lngInput}
              onChange={e => setLngInput(e.target.value)}
            />
            <button type="submit" style={{
              padding: '8px 14px', borderRadius: '8px', border: 'none', cursor: 'pointer',
              background: 'rgba(34,214,122,0.2)', color: '#22d67a', fontSize: '13px',
            }}>
              Go
            </button>
          </form>
          <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', margin: '6px 0 0' }}>
            Example: Lat 40.797, Lng -98.068
          </p>
        </div>
      )}

      {/* Draw hint */}
      {mode === 'draw' && !isComplete && (
        <div style={{
          padding: '7px 12px', fontSize: '11px', textAlign: 'center',
          background: 'rgba(34,214,122,0.05)',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: '10px', flexWrap: 'wrap', minHeight: '36px',
        }}>
          <span style={{ color: points.length >= 3 ? '#22d67a' : 'rgba(255,255,255,0.4)' }}>
            {points.length === 0 && '👆 Tap the map to place boundary points'}
            {points.length === 1 && '👆 Keep tapping to draw your boundary'}
            {points.length === 2 && '👆 Add at least one more point'}
            {points.length >= 3 && `${points.length} points placed`}
          </span>
          {points.length >= 3 && (
            <button
              onClick={() => closePolygon(mapRef.current)}
              style={{
                padding: '6px 16px', borderRadius: '8px', border: 'none',
                cursor: 'pointer', fontSize: '12px', fontWeight: '700',
                background: 'linear-gradient(135deg, #22d67a, #16a85c)',
                color: '#03081a', boxShadow: '0 2px 8px rgba(34,214,122,0.3)',
                minHeight: '32px', minWidth: '120px',
              }}
            >
              ✓ Close Boundary
            </button>
          )}
        </div>
      )}

      {/* Boundary complete */}
      {isComplete && (
        <div style={{
          padding: '7px 12px', fontSize: '11px', textAlign: 'center',
          color: '#22d67a', background: 'rgba(34,214,122,0.08)',
          borderBottom: '1px solid rgba(34,214,122,0.15)',
        }}>
          ✅ Farm boundary complete — click Analyze My Farm
        </div>
      )}

      {/* Map container */}
      <div ref={containerRef} style={{ flex: 1, minHeight: '280px' }} />

      {/* Attribution */}
      <div style={{
        padding: '4px 8px', fontSize: '9px',
        color: 'rgba(255,255,255,0.3)', textAlign: 'right',
        background: 'rgba(0,0,0,0.4)',
      }}>
        © Mapbox · © OpenStreetMap
      </div>
    </div>
  );
}