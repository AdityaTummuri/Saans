from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.config import Settings
from app.demo import demo_profile
from app.domain.forecast import (
    AirForecast,
    AirHour,
    ForecastUnavailable,
    WeatherForecast,
    WeatherHour,
    build_day_profile,
)
from app.domain.forecast import (
    WeatherHour as WH,
)
from app.domain.models import Location, TravelMode, TripOption
from app.services import air_quality, geocoding, routes, weather
from app.services.cache import TTLCache
from app.services.container import NotConfiguredError, build_services
from app.services.http import UpstreamError, build_client

KEY = "TEST-KEY-123"
HERE = Location(lat=28.61, lon=77.21)
THERE = Location(lat=28.55, lon=77.25)


def aq_entry(when: datetime, pm: float | None, **extra: object) -> dict[str, object]:
    pollutants = (
        []
        if pm is None
        else [
            {"code": "pm25", "concentration": {"value": pm, "units": "MICROGRAMS_PER_CUBIC_METER"}}
        ]
    )
    return {
        "dateTime": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "indexes": [
            {"code": "uaqi", "aqi": 40, "category": "Poor"},
            {"code": "ind_cpcb", "aqi": 310, "category": "Very Poor"},
        ],
        "pollutants": pollutants,
        "healthRecommendations": {"elderly": "Stay in.", "children": "Play later.", "junk": 3},
        **extra,
    }


# ---------------------------------------------------------------- Air Quality


@respx.mock
async def test_air_quality_request_shape_and_parsing() -> None:
    t0 = datetime(2025, 12, 10, 0, tzinfo=UTC)
    route = respx.post(air_quality.URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "hourlyForecasts": [aq_entry(t0, 250.0), aq_entry(t0 + timedelta(hours=1), 240.0)]
            },
        )
    )
    async with build_client() as http:
        client = air_quality.AirQualityClient(http, KEY, TTLCache[AirForecast](60), 48)
        result = await client.forecast(28.613939, 77.209021, "hi")
    sent = json.loads(route.calls[0].request.content)
    assert sent["location"] == {"latitude": 28.61, "longitude": 77.21}  # rounded for privacy
    assert sent["languageCode"] == "hi" and sent["pageSize"] == 48
    assert {"LOCAL_AQI", "HEALTH_RECOMMENDATIONS", "POLLUTANT_CONCENTRATION"} <= set(
        sent["extraComputations"]
    )
    assert route.calls[0].request.url.params["key"] == KEY
    assert [h.pm25 for h in result.hours] == [250.0, 240.0]
    assert result.hours[0].local_aqi == 310 and result.hours[0].local_category == "Very Poor"
    assert result.recommendations == {"elderly": "Stay in.", "children": "Play later."}


@respx.mock
async def test_air_quality_is_cached_by_rounded_location() -> None:
    t0 = datetime(2025, 12, 10, 0, tzinfo=UTC)
    route = respx.post(air_quality.URL).mock(
        return_value=httpx.Response(200, json={"hourlyForecasts": [aq_entry(t0, 100.0)]})
    )
    async with build_client() as http:
        client = air_quality.AirQualityClient(http, KEY, TTLCache[AirForecast](60))
        await client.forecast(28.611, 77.209)
        await client.forecast(28.614, 77.212)  # same 2-decimal cell
        await client.forecast(19.07, 72.87)  # different city
    assert route.call_count == 2


def test_air_quality_parse_errors() -> None:
    with pytest.raises(UpstreamError, match="no forecast"):
        air_quality.parse_forecast({})
    with pytest.raises(UpstreamError, match="no usable hours"):
        air_quality.parse_forecast({"hourlyForecasts": [{"dateTime": "garbage"}]})


@respx.mock
async def test_air_quality_http_error_is_generic() -> None:
    respx.post(air_quality.URL).mock(return_value=httpx.Response(403, json={"error": KEY}))
    async with build_client() as http:
        client = air_quality.AirQualityClient(http, KEY, TTLCache[AirForecast](60), retries=0)
        with pytest.raises(UpstreamError) as err:
            await client.forecast(28.61, 77.21)
    assert KEY not in str(err.value)


# ---------------------------------------------------------------- Weather


def wx_entry(when: datetime, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "interval": {"startTime": when.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "isDaytime": True,
        "relativeHumidity": 70,
        "visibility": {"distance": 2.0, "unit": "KILOMETERS"},
        "wind": {"speed": {"value": 3.0, "unit": "KILOMETERS_PER_HOUR"}},
        "cloudCover": 20,
    }
    base.update(kw)
    return base


@respx.mock
async def test_weather_request_and_parse_with_unit_conversion() -> None:
    t0 = datetime(2025, 12, 10, 0, tzinfo=UTC)
    route = respx.get(weather.URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "timeZone": {"id": "Asia/Kolkata"},
                "forecastHours": [
                    wx_entry(
                        t0,
                        visibility={"distance": 1.0, "unit": "MILES"},
                        wind={"speed": {"value": 10.0, "unit": "MILES_PER_HOUR"}},
                    )
                ],
            },
        )
    )
    async with build_client() as http:
        client = weather.WeatherClient(http, KEY, TTLCache[WeatherForecast](60), 48)
        result = await client.forecast(28.613939, 77.209021)
    params = route.calls[0].request.url.params
    assert params["hours"] == "48" and params["location.latitude"] == "28.61"
    assert result.timezone == "Asia/Kolkata"
    hour = result.hours[0]
    assert hour.wind_kmh == pytest.approx(16.09344)
    assert hour.visibility_km == pytest.approx(1.609344)
    assert hour.humidity_pct == 70 and hour.cloud_cover_pct == 20 and hour.is_daytime is True


def test_weather_parse_errors() -> None:
    with pytest.raises(UpstreamError):
        weather.parse_forecast({"forecastHours": []})
    with pytest.raises(UpstreamError, match="no usable hours"):
        weather.parse_forecast({"forecastHours": [{"interval": {}}]})


# ---------------------------------------------------------------- Routes


def test_routes_request_body_per_mode() -> None:
    body = routes.request_body(HERE, THERE, TravelMode.CAR)
    assert body["travelMode"] == "DRIVE" and body["routingPreference"] == "TRAFFIC_AWARE"
    assert routes.request_body(HERE, THERE, TravelMode.AUTO_RICKSHAW)["travelMode"] == "DRIVE"
    assert routes.request_body(HERE, THERE, TravelMode.TWO_WHEELER)["travelMode"] == "TWO_WHEELER"
    metro = routes.request_body(HERE, THERE, TravelMode.METRO)
    assert (
        metro["travelMode"] == "TRANSIT"
        and "SUBWAY" in metro["transitPreferences"]["allowedTravelModes"]
    )
    assert routes.request_body(HERE, THERE, TravelMode.BUS)["transitPreferences"] == {
        "allowedTravelModes": ["BUS"]
    }
    assert "routingPreference" not in routes.request_body(HERE, THERE, TravelMode.WALK)


@respx.mock
async def test_routes_options_skip_modes_without_a_route() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        mode = json.loads(request.content)["travelMode"]
        if mode == "TRANSIT":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"routes": [{"duration": "1200s", "distanceMeters": 5000}]})

    route = respx.post(routes.URL).mock(side_effect=answer)
    async with build_client() as http:
        client = routes.RoutesClient(http, KEY, TTLCache[TripOption](60))
        opts = await client.options(
            HERE, THERE, [TravelMode.CAR, TravelMode.WALK, TravelMode.METRO]
        )
    assert {o.mode for o in opts} == {TravelMode.CAR, TravelMode.WALK}
    car = next(o for o in opts if o.mode == TravelMode.CAR)
    assert car.duration_min == pytest.approx(20) and car.distance_km == pytest.approx(5)
    sent = route.calls[0].request
    assert sent.headers["X-Goog-Api-Key"] == KEY
    assert "routes.duration" in sent.headers["X-Goog-FieldMask"]
    assert KEY not in str(sent.url)


@respx.mock
async def test_routes_all_modes_failing_raises() -> None:
    respx.post(routes.URL).mock(return_value=httpx.Response(500))
    async with build_client() as http:
        client = routes.RoutesClient(http, KEY, TTLCache[TripOption](60), retries=0)
        with pytest.raises(UpstreamError, match="no route"):
            await client.options(HERE, THERE, [TravelMode.CAR])


def test_routes_parse_errors() -> None:
    with pytest.raises(UpstreamError, match="no route"):
        routes.parse_option({"routes": []}, TravelMode.CAR)
    with pytest.raises(UpstreamError, match="malformed"):
        routes.parse_option({"routes": [{"distanceMeters": 5}]}, TravelMode.CAR)


# ---------------------------------------------------------------- Geocoding


@respx.mock
async def test_geocoding_success_rounds_and_caches() -> None:
    route = respx.get(geocoding.URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "Connaught Place, New Delhi",
                        "geometry": {"location": {"lat": 28.631451, "lng": 77.216667}},
                    }
                ],
            },
        )
    )
    async with build_client() as http:
        client = geocoding.GeocodingClient(http, KEY, TTLCache[Location](60))
        loc = await client.geocode("  Connaught   Place ")
        await client.geocode("connaught place")
    assert (loc.lat, loc.lon) == (28.63, 77.22) and "Connaught" in loc.label
    assert route.call_count == 1
    assert route.calls[0].request.url.params["address"] == "Connaught Place"


@respx.mock
async def test_geocoding_failures() -> None:
    respx.get(geocoding.URL).mock(
        return_value=httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})
    )
    async with build_client() as http:
        client = geocoding.GeocodingClient(http, KEY, TTLCache[Location](60))
        with pytest.raises(UpstreamError, match="not found"):
            await client.geocode("zzzz")
        with pytest.raises(UpstreamError, match="empty"):
            await client.geocode("   ")


# ---------------------------------------------------------------- Day profile


def air(hours: list[tuple[datetime, float | None]]) -> AirForecast:
    return AirForecast(hours=[AirHour(time=t, pm25=p) for t, p in hours])


def test_profile_converts_utc_to_local_using_weather_zone() -> None:
    # 18:30 UTC is 00:00 in Asia/Kolkata
    t0 = datetime(2025, 12, 9, 18, 30, tzinfo=UTC)
    forecast = air([(t0 + timedelta(hours=i), float(100 + i)) for i in range(48)])
    wx = WeatherForecast(
        timezone="Asia/Kolkata",
        hours=[
            WeatherHour(time=t0 + timedelta(hours=i), is_daytime=(7 <= i % 24 <= 17), wind_kmh=5)
            for i in range(48)
        ],
    )
    profile = build_day_profile(forecast, wx)
    assert profile.at(0).pm25 == 100.0  # first entry is local midnight
    assert profile.at(13).pm25 == 113.0
    assert profile.at(10).is_daytime and not profile.at(22).is_daytime
    assert profile.at(5).wind_kmh == 5


def test_profile_uses_the_next_occurrence_of_each_local_hour() -> None:
    # forecast starts at local 20:00 so hour 5 should come from the next morning
    t0 = datetime(2025, 12, 10, 14, 30, tzinfo=UTC)  # 20:00 IST
    forecast = air([(t0 + timedelta(hours=i), float(i)) for i in range(30)])
    profile = build_day_profile(
        forecast, WeatherForecast(timezone="Asia/Kolkata", hours=[WH(time=t0)])
    )
    assert profile.at(20).pm25 == 0.0
    assert profile.at(5).pm25 == 9.0


def test_profile_fills_gaps_and_defaults_without_weather() -> None:
    t0 = datetime(2025, 12, 10, 0, tzinfo=UTC)
    forecast = air([(t0 + timedelta(hours=i), 100.0 if i % 2 == 0 else None) for i in range(48)])
    profile = build_day_profile(forecast, WeatherForecast(timezone="Not/AZone", hours=[]))
    assert all(h.pm25 == 100.0 for h in profile.hours)
    assert profile.at(12).is_daytime and not profile.at(2).is_daytime  # fallback day/night


def test_profile_needs_enough_hours() -> None:
    t0 = datetime(2025, 12, 10, 0, tzinfo=UTC)
    with pytest.raises(ForecastUnavailable):
        build_day_profile(
            air([(t0 + timedelta(hours=i), 90.0) for i in range(5)]),
            WeatherForecast(timezone="UTC", hours=[]),
        )


# ---------------------------------------------------------------- Demo mode


async def test_demo_services_reproduce_the_demo_profile() -> None:
    services = build_services(Settings(demo_mode=True, _env_file=None))  # type: ignore[call-arg]
    try:
        air_fc = await services.air.forecast(28.61, 77.21)
        wx_fc = await services.weather.forecast(28.61, 77.21)
        profile = build_day_profile(air_fc, wx_fc)
        expected = demo_profile()
        assert [h.pm25 for h in profile.hours] == [h.pm25 for h in expected.hours]
        assert [h.is_daytime for h in profile.hours] == [h.is_daytime for h in expected.hours]
        assert air_fc.recommendations["elderly"]
        loc = await services.geocoder.geocode("anywhere")
        assert (loc.lat, loc.lon) == (28.61, 77.21)
        opts = await services.routes.options(
            HERE, THERE, [TravelMode.CAR, TravelMode.METRO, TravelMode.BUS, TravelMode.WALK]
        )
        assert len(opts) == 4
        metro = next(o for o in opts if o.mode == TravelMode.METRO)
        bus = next(o for o in opts if o.mode == TravelMode.BUS)
        assert metro.duration_min != bus.duration_min
    finally:
        await services.aclose()


def test_live_mode_requires_a_maps_key() -> None:
    with pytest.raises(NotConfiguredError):
        build_services(Settings(demo_mode=False, maps_api_key=None, _env_file=None))  # type: ignore[call-arg]
