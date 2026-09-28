# Georeferencing

Positions inside the stack are metres in the venue frame: origin at the lower-left
corner of the floor plan, x along its width, y along its depth, z up from the
floor. An adapter may report in the frame of one room, and the engine places the
room in the floor plan. Latitude and longitude appear at two points only. The
floor plan's `georef` ties the venue frame to the Earth, and the engine converts
each position to WGS84 for the CAMARA response. A vendor position in WGS84 is
converted into the venue frame with the inverse transform.

## The georef

```json
{
  "latitude": 59.404210,
  "longitude": 17.949278,
  "azimuth_deg": -36.445,
  "width_m": 118.8,
  "depth_m": 110.9,
  "calibrated_against": "mapbox",
  "calibration_points": 4,
  "calibration_rms_m": 0.41
}
```

| Field | Meaning |
|-------|---------|
| `latitude`, `longitude` | the venue origin, the lower-left corner of the floor plan |
| `azimuth_deg` | the bearing of the venue +y axis from true north, clockwise |
| `width_m`, `depth_m` | the size of the floor plan |
| `altitude_m` | the ellipsoidal height of the venue floor, present only when surveyed. A CAMARA response carries an altitude only when this is set and the source measures height |
| `calibrated_against` | the basemap the world alignment was fitted on: `mapbox`, `google-satellite`, `google-hybrid`, `esri` or `osm-carto` |
| `calibration_points` | the number of point pairs in that fit |
| `calibration_rms_m` | the root-mean-square residual of the fit, in metres |

The last three fields record provenance. No computation reads them.

The engine converts with an equirectangular approximation at 111 320 m per
degree. At the latitude of Stockholm this differs from the WGS84 ellipsoid by
0.07 % north-south and 0.25 % east-west, up to 25 cm across 100 m.

## Absolute accuracy

The venue frame is as accurate as the measurements of the building. The tie to
the Earth is as accurate as the reference it was fitted on, and three effects
limit it:

1. **Map tiles are registered independently.** Each imagery provider
   orthorectifies against its own terrain model and control points. Offsets of
   1 to 5 m between providers are common in urban areas, and the providers
   disagree on the same building.
2. **A vendor cloud inherits its basemap.** An RTLS vendor that places anchors
   on its own map, such as Wittra on Mapbox, reports coordinates consistent
   with that map. A floor plan aligned on another provider disagrees with the
   vendor by the offset between the two.
3. **Reference frames drift apart.** WGS84 follows the Earth's centre of mass.
   SWEREF 99, the Swedish realisation of ETRS89, moves with the Eurasian plate,
   which drifts about 2.5 cm per year against WGS84. The two now differ by
   0.8 to 0.9 m. The stack emits WGS84 and applies no datum transformation.

Relative accuracy, between anchors and between a device and its room, depends
only on the venue frame.

## Calibration in the placement editor

Three quantities are fixed in order.

### Image scale, Plan section

An architectural drawing has no known pixel size. The scale tool takes two
points on the drawing and the distance between them, such as a corridor or a
dimension line. The reference pairs are stored in the floor plan
(`scale_calibration_refs`) and can be reapplied. A longer reference divides the
same click error by a longer baseline: a 20 m corridor gives a better scale
than a 90 cm door.

### World alignment, World section

The N-point calibrate tool fits a similarity transform (rotation, uniform scale,
translation) between the floor plan and the basemap. Each pair is a landmark
clicked on the drawing and the same feature clicked on the map.

- Two pairs fit exactly and show no error. From the third pair on the fit is a
  least-squares fit, and the panel shows each pair's residual in metres and the
  RMS.
- Pairs far apart, such as opposite corners of the building, constrain the
  rotation better than pairs along one wall.
- A pair whose residual exceeds 1.5 m is highlighted: a wrong click or a
  misidentified feature.
- The fit's scale factor should stay close to 1 after a careful image scale.
  A large correction points to a wrong pair.
- The basemap is chosen in the layer switcher. To compare with a vendor cloud,
  align on the vendor's provider. A Mapbox layer appears when
  `VITE_MAPBOX_TOKEN` is set.

### Anchor positions, Room section

Anchors are placed in room metres, from measurements taken in the room. The
georef does not affect them. Anchors imported from a vendor cloud are
converted from the vendor's WGS84 through the georef, so their error adds the
vendor's placement error to the offset between the vendor's basemap and
`calibrated_against`. The sync panel shows imported positions and their drift
from existing anchors before import.

## Surveyed references

The N-point tool takes its world points from the basemap, so the alignment
carries the basemap's registration error. Surveyed coordinates remove it: a
building corner from Lantmäteriet's cadastral map, or a network RTK fix from
SWEPOS, both with centimetre accuracy. The World sidebar accepts latitude,
longitude, azimuth and altitude as numbers, so a georef computed from surveyed
points is entered there. Cadastral and RTK coordinates are in SWEREF 99 and
differ from WGS84 by the frame drift above.

The `📍 ref point` tool marks points on the map and lists their coordinates, to
compare the alignment with the same points in a vendor portal.
