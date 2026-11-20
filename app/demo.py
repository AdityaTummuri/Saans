"""The demo household (a Delhi family of four) and a representative winter-day profile.

The profile is a recorded-style shape for keyless demos and tests: heavy overnight smog under
calm, humid air, a midday trough, and an evening rise.
"""

from __future__ import annotations

from app.domain.models import (
    Activity,
    AgeBand,
    BudgetTier,
    Condition,
    DayProfile,
    Home,
    HomeSource,
    HourlyConditions,
    Household,
    Intensity,
    Language,
    Location,
    LocationType,
    Member,
    Room,
    SourceUse,
    TravelMode,
    Trip,
    TripOption,
    WindowType,
)

_PM25 = [
    290, 295, 300, 305, 310, 315, 320, 310, 290, 250, 210, 170,
    145, 140, 140, 170, 240, 280, 305, 310, 305, 300, 295, 292,
]  # fmt: skip


def demo_profile() -> DayProfile:
    """A 24-hour Delhi winter profile (ug/m^3 PM2.5 plus weather) indexed by clock hour."""
    hours: list[HourlyConditions] = []
    for h, pm in enumerate(_PM25):
        daytime = 7 <= h <= 17
        midday = 11 <= h <= 15
        hours.append(
            HourlyConditions(
                hour=h,
                pm25=float(pm),
                wind_kmh=9.0 if midday else 4.0 if daytime else 2.0,
                humidity_pct=45.0 if midday else 65.0 if daytime else 88.0,
                visibility_km=5.0 if midday else 2.5 if daytime else 1.2,
                cloud_cover_pct=15.0,
                is_daytime=daytime,
            )
        )
    return DayProfile(hours=hours)


def demo_household(language: Language = Language.EN) -> Household:
    """Grandfather with COPD, two working parents, and an eight-year-old footballer."""
    return Household(
        location=Location(lat=28.61, lon=77.21, label="New Delhi"),
        members=[
            Member(id="dadaji", name="Dadaji", age_band=AgeBand.OLDER, conditions=[Condition.COPD]),
            Member(id="meera", name="Meera", age_band=AgeBand.ADULT),
            Member(id="rohan", name="Rohan", age_band=AgeBand.ADULT),
            Member(id="aarav", name="Aarav", age_band=AgeBand.CHILD),
        ],
        activities=[
            Activity(
                id="football",
                name="Football practice",
                member_ids=["aarav"],
                duration_h=1.0,
                intensity=Intensity.VIGOROUS,
                location=LocationType.OUTDOOR,
                start_hour=16.0,
                window_start=12.0,
                window_end=18.0,
            ),
            Activity(
                id="walk",
                name="Morning walk",
                member_ids=["dadaji"],
                duration_h=0.75,
                intensity=Intensity.LIGHT,
                location=LocationType.OUTDOOR,
                start_hour=6.5,
                window_start=6.0,
                window_end=12.0,
            ),
        ],
        trips=[
            Trip(
                id="office",
                name="Meera's office commute",
                member_ids=["meera"],
                mode=TravelMode.AUTO_RICKSHAW,
                depart_hour=8.5,
                depart_flex_h=1.0,
                options=[
                    TripOption(mode=TravelMode.AUTO_RICKSHAW, duration_min=35, distance_km=11),
                    TripOption(mode=TravelMode.METRO, duration_min=45, distance_km=12),
                    TripOption(mode=TravelMode.BUS, duration_min=55, distance_km=11),
                    TripOption(mode=TravelMode.CAR, duration_min=40, distance_km=11),
                ],
            ),
            Trip(
                id="school",
                name="School run",
                member_ids=["rohan", "aarav"],
                mode=TravelMode.CAR,
                depart_hour=7.5,
                options=[
                    TripOption(mode=TravelMode.CAR, duration_min=25, distance_km=7),
                    TripOption(mode=TravelMode.AUTO_RICKSHAW, duration_min=28, distance_km=7),
                ],
            ),
        ],
        home=Home(
            rooms=[
                Room(
                    name="Parents' bedroom",
                    volume_m3=36,
                    windows=WindowType.LEAKY,
                    occupant_ids=["meera", "rohan"],
                ),
                Room(
                    name="Dadaji's room",
                    volume_m3=30,
                    windows=WindowType.LEAKY,
                    occupant_ids=["dadaji"],
                    occupied_from=21,
                    occupied_to=8,
                ),
                Room(
                    name="Kids' room",
                    volume_m3=27,
                    windows=WindowType.SEALED,
                    purifier_cadr_m3_per_h=0.0,
                    occupant_ids=["aarav"],
                    occupied_from=21,
                    occupied_to=7,
                ),
                Room(
                    name="Living room",
                    volume_m3=60,
                    windows=WindowType.LEAKY,
                    occupant_ids=["dadaji", "meera", "rohan", "aarav"],
                    occupied_from=18,
                    occupied_to=21,
                ),
            ],
            sources=[
                SourceUse(kind=HomeSource.INCENSE, hours_per_day=0.5, room="Living room"),
                SourceUse(kind=HomeSource.WASTE_BURNING, hours_per_day=0.5),
            ],
        ),
        budget=BudgetTier.MEDIUM,
        language=language,
    )
