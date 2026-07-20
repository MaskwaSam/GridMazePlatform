# Grid Maze Platform 3D Print Optimization

Profile: `balanced`

## Baseline

- tile 200 x 200 x 10.0 mm, pocket 8.0 mm, skin 2.0 mm, dovetail 50 x 22/46 mm, connector 6.0 mm, clearance 0.20 mm, sides north,south,east,west
- Baseline score: 10.00
- clearance 0.20 mm, dovetail 50 x 22/46 mm, connector 6.0 mm, slack 2.0 mm, angle 13.5 deg
- Warning: 0.20 mm clearance is a tuned-printer fit; print a connector coupon first

## Printability Checks

- `pass` platform stack is 10 mm total, 8 mm underside recess, 2 mm top skin
- `review` pocket clearance is 0.20 mm per side
- `pass` connector sits 2.0 mm below the pocket roof
- `pass` dovetail taper angle is 13.5 degrees per side
- `info` 4 selected side pocket(s): north, south, east, west
- `info` estimated bridge volume is 20.4 cm3
- `info` estimated selected pocket removal is 55.3 cm3

## Recommended Variant

- Score: 0.00
- tile 200 x 200 x 10.0 mm, pocket 8.0 mm, skin 2.0 mm, dovetail 50 x 22/42 mm, connector 6.0 mm, clearance 0.25 mm, sides north,south,east,west
- clearance 0.25 mm, dovetail 50 x 22/42 mm, connector 6.0 mm, slack 2.0 mm, angle 11.3 deg

## Top Candidates

1. score 0.00: clearance 0.25 mm, dovetail 50 x 22/42 mm, connector 6.0 mm, slack 2.0 mm, angle 11.3 deg
2. score 0.00: clearance 0.25 mm, dovetail 50 x 22/44 mm, connector 6.0 mm, slack 2.0 mm, angle 12.4 deg
3. score 0.00: clearance 0.25 mm, dovetail 50 x 22/46 mm, connector 6.0 mm, slack 2.0 mm, angle 13.5 deg
4. score 0.00: clearance 0.25 mm, dovetail 50 x 22/48 mm, connector 6.0 mm, slack 2.0 mm, angle 14.6 deg
5. score 0.00: clearance 0.25 mm, dovetail 50 x 22/50 mm, connector 6.0 mm, slack 2.0 mm, angle 15.6 deg
6. score 0.16: clearance 0.25 mm, dovetail 50 x 20/42 mm, connector 6.0 mm, slack 2.0 mm, angle 12.4 deg
7. score 0.16: clearance 0.25 mm, dovetail 50 x 24/42 mm, connector 6.0 mm, slack 2.0 mm, angle 10.2 deg
8. score 0.16: clearance 0.25 mm, dovetail 50 x 20/44 mm, connector 6.0 mm, slack 2.0 mm, angle 13.5 deg

## Practical Notes

- Keep printing the connector flat on the bed; this design has no intentional overhang lock.
- Print one bridge plus a short edge-pocket coupon before committing to full tiles.
- Use the `tight` profile if your printer reliably handles 0.20 mm clearance.
- Use the `balanced` profile for a more forgiving first FDM prototype.
- The optimizer does not overwrite `params/maze_platform_v1.json`; use `--write-params` to create a separate optimized JSON.
