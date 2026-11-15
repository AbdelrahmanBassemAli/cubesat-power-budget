# CubeSat Power Budget

[![selftest](https://github.com/AbdelrahmanBassemAli/cubesat-power-budget/actions/workflows/ci.yml/badge.svg)](https://github.com/AbdelrahmanBassemAli/cubesat-power-budget/actions)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AbdelrahmanBassemAli/cubesat-power-budget/blob/main/CubeSat_Power_Budget.ipynb)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A first-order, orbit-average **power budget calculator for CubeSats** in Python. It answers the first question an electrical power subsystem (EPS) designer asks: *does the energy collected in sunlight cover the load and recharge the battery for the eclipse?*

![Animation: tumbling 1U CubeSat](docs/power_animation.gif)

*Default tumbling 1U design at 500 km, beta 0 deg: generation drops to zero in eclipse and the battery loses charge orbit after orbit, so the design does not close.*

## What it computes
- Orbital period and eclipse duration for a circular orbit, including the effect of the **beta angle**
- Solar generation for a **tumbling** or **sun-pointing** satellite (body-mounted and deployable panels)
- Energy balance per orbit with EPS and battery losses, and the resulting power margin
- Required battery capacity for a chosen depth of discharge, and battery cycles per year
- A beta-angle sweep (0-90 deg) that finds the worst case
- A time-domain simulation of the battery state of charge, with an animated GIF

## Quick start
```bash
git clone https://github.com/AbdelrahmanBassemAli/cubesat-power-budget.git
cd cubesat-power-budget
pip install -r requirements.txt

python cubesat_power_budget.py --selftest
python cubesat_power_budget.py --alt 500 --beta 0
python cubesat_power_budget.py --animate --orbits 3
python cubesat_power_budget.py --attitude sun_pointing --deployed-area 0.02 --animate
python cubesat_power_budget.py --config config.example.json
```
Or run it in the browser with the Colab badge above. Outputs go to `results/`: `power_budget_beta_sweep.png`, `summary.json`, and with `--animate` also `power_animation.gif`.

## Example result (default 1U assumptions, 500 km, beta 0)
| Quantity | Tumbling, 4 cell faces | Sun-pointing + 0.02 m^2 deployed |
|---|---|---|
| Orbit period | 94.6 min | 94.6 min |
| Eclipse / sunlight | 35.8 / 58.9 min | 35.8 / 58.9 min |
| Orbit-average load | 1.29 W | 1.29 W |
| Power margin | -18.1 % (does not close) | +145.6 % |
| Battery for 30 % DoD | 2.79 Wh | 2.79 Wh |

![Sun-pointing design](docs/power_animation_sun_pointing.gif)

The beta-angle sweep shows the worst case is beta 0 and that eclipses disappear above about 68 deg at this altitude:

![Beta sweep](docs/power_budget_beta_sweep.png)

## Method
- Period: `T = 2*pi*sqrt(a^3 / mu)`, with `a = Re + h`
- Eclipse (cylindrical shadow): `T_ecl = (T/pi) * arccos( sqrt(h^2 + 2*Re*h) / ((Re+h) * cos(beta)) )`, zero above the critical beta angle
- Tumbling generation: the mean projected area of each face is `A/4`
- Energy balance: `E_gen = P_sun * eta_eps * T_sun` against `E_load_sun + E_load_eclipse / eta_batt^2` (eclipse energy passes through the battery twice)
- Battery: `E_eclipse_load / (DoD * eta_discharge)`
- Simulation: step through orbits, mark eclipse when `cos(theta) < 0` and `a^2 (1 - cos^2(theta) cos^2(beta)) < Re^2`, and update the state of charge with charge/discharge efficiency

## Configuration
Every default is an **assumption for a generic 1U CubeSat**. Copy `config.example.json`, put in your own cell efficiency, panel area and loads, and pass it with `--config`. Do not quote the default numbers as results of a specific mission.

## Validation
`--selftest` checks the orbit and eclipse formulas against textbook values (500 km: ~94.6 min period, ~35.8 min maximum eclipse), the tumbling-area model, the no-eclipse case, and that the time simulation agrees with the analytic eclipse fraction. CI runs it on every push.

## Limitations
- Circular orbit and cylindrical Earth shadow (no penumbra)
- No cell-angle or temperature dependence, no seasonal solar-constant variation
- Loads are duty-cycle averages, not a time-resolved mode schedule
- Sun-pointing assumes perfect pointing

## References
- Wertz & Larson, *Space Mission Analysis and Design* (orbit, eclipse and power-system sizing)
- Kopp & Lean (2011), "A new, lower value of total solar irradiance", *Geophysical Research Letters* 38, L01706, doi:10.1029/2010GL045777 (solar constant 1361 W/m^2)

## Development note
Written with AI assistance (Claude) and verified with the included self-tests.

## License
MIT. See [LICENSE](LICENSE).
