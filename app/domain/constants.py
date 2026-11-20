"""Every tunable number the engine uses, with the reasoning behind it.

Values marked "assumption" are population-average defaults chosen conservatively; they are
documented in the README and can be overridden in one place. Nothing here does I/O.
"""

from __future__ import annotations

from typing import Final

from app.domain.models import (
    AgeBand,
    BudgetTier,
    Condition,
    HomeSource,
    Intensity,
    TravelMode,
)

# ---------------------------------------------------------------------------------------------
# Breathing rate VE, m^3/h, by age band and intensity.
# Source: US EPA Exposure Factors Handbook (2011), Chapter 6 (inhalation rates), rounded to the
# scale in the plan: adult ~0.5 rest, ~1 light, ~1.75 moderate, ~3 vigorous. Child and infant
# rows are scaled from the handbook's age-specific tables.
# ---------------------------------------------------------------------------------------------
BREATHING_RATE_M3_PER_H: Final[dict[AgeBand, dict[Intensity, float]]] = {
    AgeBand.INFANT: {
        Intensity.REST: 0.20,
        Intensity.LIGHT: 0.30,
        Intensity.MODERATE: 0.50,
        Intensity.VIGOROUS: 0.80,
    },
    AgeBand.CHILD: {
        Intensity.REST: 0.40,
        Intensity.LIGHT: 0.80,
        Intensity.MODERATE: 1.50,
        Intensity.VIGOROUS: 2.40,
    },
    AgeBand.TEEN: {
        Intensity.REST: 0.50,
        Intensity.LIGHT: 1.00,
        Intensity.MODERATE: 1.75,
        Intensity.VIGOROUS: 2.80,
    },
    AgeBand.ADULT: {
        Intensity.REST: 0.50,
        Intensity.LIGHT: 1.00,
        Intensity.MODERATE: 1.75,
        Intensity.VIGOROUS: 3.00,
    },
    AgeBand.OLDER: {
        Intensity.REST: 0.45,
        Intensity.LIGHT: 0.90,
        Intensity.MODERATE: 1.50,
        Intensity.VIGOROUS: 2.40,
    },
}

# ---------------------------------------------------------------------------------------------
# Microenvironment factor MEF: exposure relative to ambient PM2.5 at the monitor.
# Assumption: representative mid-points of ranges reported in published commute-exposure
# studies for South Asian cities (open vehicles and roadside walking see more than ambient;
# closed, air-conditioned or recirculating spaces see less).
# ---------------------------------------------------------------------------------------------
MEF_OUTDOOR: Final[float] = 1.0
MEF_ROADSIDE: Final[float] = 1.15
MEF_INDOOR_DEFAULT: Final[float] = 0.6  # leaky home with no purifier, assumption

MEF_BY_MODE: Final[dict[TravelMode, float]] = {
    TravelMode.WALK: 1.15,
    TravelMode.CYCLE: 1.20,
    TravelMode.TWO_WHEELER: 1.30,
    TravelMode.AUTO_RICKSHAW: 1.40,
    TravelMode.BUS: 1.20,
    TravelMode.CAR: 0.90,  # windows partly open
    TravelMode.METRO: 0.70,
}
MEF_CAR_RECIRCULATION: Final[float] = 0.60  # cabin recirculation with closed windows

# Breathing intensity while travelling in each mode (seated passengers breathe near rest).
INTENSITY_BY_MODE: Final[dict[TravelMode, Intensity]] = {
    TravelMode.WALK: Intensity.LIGHT,
    TravelMode.CYCLE: Intensity.MODERATE,
    TravelMode.TWO_WHEELER: Intensity.LIGHT,
    TravelMode.AUTO_RICKSHAW: Intensity.REST,
    TravelMode.BUS: Intensity.REST,
    TravelMode.CAR: Intensity.REST,
    TravelMode.METRO: Intensity.REST,
}

# Mask factor MF. A fitted N95 filters >=95% in the lab; real-world leakage and imperfect
# fit make a conservative effective factor of 0.4 (assumption).
MASK_FACTOR: Final[float] = 0.4
# Masks are not recommended for infants (suffocation risk).
MASK_EXCLUDED_AGE_BANDS: Final[frozenset[AgeBand]] = frozenset({AgeBand.INFANT})
# Only suggest a mask when the average PM2.5 during the exposure is at least this high.
MASK_MIN_PM25: Final[float] = 60.0

# ---------------------------------------------------------------------------------------------
# Scheduler and ranking rules (plan section 6).
# ---------------------------------------------------------------------------------------------
MIN_SAVING_FRACTION: Final[float] = 0.10  # below this, keep the original routine
DAYLIGHT_ONLY_AGE_BANDS: Final[frozenset[AgeBand]] = frozenset({AgeBand.INFANT, AgeBand.CHILD})

VULNERABILITY_BASE: Final[dict[AgeBand, float]] = {
    AgeBand.INFANT: 1.5,
    AgeBand.CHILD: 1.5,
    AgeBand.TEEN: 1.0,
    AgeBand.ADULT: 1.0,
    AgeBand.OLDER: 1.3,
}
VULNERABILITY_CONDITION: Final[dict[Condition, float]] = {
    Condition.PREGNANCY: 1.5,
    Condition.ASTHMA: 2.0,
    Condition.COPD: 2.0,
    Condition.HEART_DISEASE: 2.0,
}

# Effort tiers: 1 free or a shift, 2 habit or low cost, 3 do-it-yourself, 4 purchase.
TIER_FREE: Final[int] = 1
TIER_HABIT: Final[int] = 2
TIER_DIY: Final[int] = 3
TIER_PURCHASE: Final[int] = 4
LOW_BUDGET_MAX_TIER: Final[int] = TIER_DIY

# Berkeley Earth: 22 ug/m^3 averaged over 24 hours is roughly one cigarette. Communication
# heuristic only, never a medical statement.
CIGARETTE_UG_M3_HOURS: Final[float] = 22.0 * 24.0

# ---------------------------------------------------------------------------------------------
# India NAQI (CPCB) PM2.5 bands: (upper bound ug/m^3, category key).
# ---------------------------------------------------------------------------------------------
NAQI_PM25_BANDS: Final[tuple[tuple[float, str], ...]] = (
    (30.0, "good"),
    (60.0, "satisfactory"),
    (90.0, "moderate"),
    (120.0, "poor"),
    (250.0, "very_poor"),
    (float("inf"), "severe"),
)
NAQI_ORDER: Final[tuple[str, ...]] = tuple(name for _, name in NAQI_PM25_BANDS)
# "Avoid exertion" starts at Poor for the general population and one category earlier
# (Moderate) for sensitive members.
AVOID_EXERTION_FROM: Final[str] = "poor"

# ---------------------------------------------------------------------------------------------
# Smog Stagnation Index weights (heuristic, covered by tests). Plan section 6.
# ---------------------------------------------------------------------------------------------
SSI_WIND_CALM_KMH: Final[float] = 15.0
SSI_HUMIDITY_FLOOR: Final[float] = 50.0
SSI_VISIBILITY_CLEAR_KM: Final[float] = 10.0
SSI_DAY_INVERSION: Final[float] = 0.3
SSI_WEIGHTS: Final[dict[str, float]] = {
    "wind": 0.40,
    "humidity": 0.20,
    "visibility": 0.15,
    "inversion": 0.25,
}

# ---------------------------------------------------------------------------------------------
# Indoor mass balance. P=0.9 and k=0.3 reproduce the worked example in the plan
# (36 m^3 room, 250 ug/m^3 outdoors: ~173 leaky, ~33 with CADR 200, ~18 sealed + CADR 200).
# ---------------------------------------------------------------------------------------------
PENETRATION_FACTOR: Final[float] = 0.9  # P, typical range 0.8 to 1.0
DEPOSITION_RATE_PER_H: Final[float] = 0.3  # k, typical range 0.2 to 0.4 per hour
AIR_EXCHANGE_LEAKY_PER_H: Final[float] = 1.0
AIR_EXCHANGE_SEALED_PER_H: Final[float] = 0.5
INDOOR_TARGET_PM25: Final[float] = 30.0  # top of the NAQI "Good" band
# Corsi-Rosenthal box (box fan plus four filters). Measured CADRs are often higher; this is a
# conservative assumption.
CR_BOX_CADR_M3_PER_H: Final[float] = 200.0
PURIFIER_CADR_STEP: Final[float] = 50.0  # round purchase recommendations up to this step
# Hours of day considered for airing the house out.
VENTILATION_FIRST_HOUR: Final[int] = 6
VENTILATION_LAST_HOUR: Final[int] = 21
VENTILATION_MINUTES: Final[int] = 15

# Indoor source strength S in ug of PM2.5 per hour of use.
# Assumption: order-of-magnitude values from indoor-air chamber studies, rounded.
SOURCE_STRENGTH_UG_PER_H: Final[dict[HomeSource, float]] = {
    HomeSource.INCENSE: 3_000.0,
    HomeSource.MOSQUITO_COIL: 25_000.0,
    HomeSource.FRYING: 5_000.0,
    HomeSource.DIYA: 1_500.0,
    HomeSource.WOOD_COOKING: 40_000.0,
}
# Sources that mostly pollute the neighbourhood rather than the room.
OUTDOOR_SOURCES: Final[frozenset[HomeSource]] = frozenset(
    {HomeSource.WASTE_BURNING, HomeSource.COAL_HEATING, HomeSource.FIRECRACKERS}
)

# ---------------------------------------------------------------------------------------------
# Emission factors per passenger-km. Assumption: representative averages for Indian road
# transport (petrol car with a single occupant, CNG auto, small two-wheeler, city bus, metro
# on grid electricity). PM2.5 is given only where a representative figure exists.
# ---------------------------------------------------------------------------------------------
CO2_KG_PER_PASSENGER_KM: Final[dict[TravelMode, float]] = {
    TravelMode.WALK: 0.0,
    TravelMode.CYCLE: 0.0,
    TravelMode.TWO_WHEELER: 0.035,
    TravelMode.AUTO_RICKSHAW: 0.075,
    TravelMode.CAR: 0.170,
    TravelMode.BUS: 0.030,
    TravelMode.METRO: 0.025,
}
PM25_G_PER_PASSENGER_KM: Final[dict[TravelMode, float]] = {
    TravelMode.WALK: 0.0,
    TravelMode.CYCLE: 0.0,
    TravelMode.TWO_WHEELER: 0.008,
    TravelMode.CAR: 0.004,
}

# Household sources that burn things: kg CO2 and g PM2.5 per hour of burning (assumption,
# representative of small open fires and sigris).
SOURCE_CO2_KG_PER_H: Final[dict[HomeSource, float]] = {
    HomeSource.WASTE_BURNING: 4.5,
    HomeSource.COAL_HEATING: 2.4,
    HomeSource.WOOD_COOKING: 1.8,
    HomeSource.FIRECRACKERS: 0.2,
}
SOURCE_PM25_G_PER_H: Final[dict[HomeSource, float]] = {
    HomeSource.WASTE_BURNING: 40.0,
    HomeSource.COAL_HEATING: 6.0,
    HomeSource.WOOD_COOKING: 12.0,
    HomeSource.FIRECRACKERS: 15.0,
}

DEFAULT_BUDGET: Final[BudgetTier] = BudgetTier.MEDIUM
