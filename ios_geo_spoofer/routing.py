from __future__ import annotations

import json
import math
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving/{start};{end}"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
EARTH_RADIUS_METERS = 6_371_000
MAX_ROUTE_POINTS = 20_000
MIN_AUTO_SPEED_MPS = 2.2352
MAX_AUTO_SPEED_MPS = 40.2336


@dataclass(frozen=True)
class RoadRoute:
    coordinates: list[tuple[float, float]]
    distance_meters: float
    segment_speeds_mps: list[float]


@dataclass(frozen=True)
class RoutePoint:
    latitude: float
    longitude: float
    elapsed_seconds: float


@dataclass(frozen=True)
class RoutePlan:
    coordinates: list[tuple[float, float]]
    distance_meters: float
    duration_seconds: float
    gpx_path: Path
    used_auto_speed: bool
    stop_count: int


@dataclass(frozen=True)
class FlightStage:
    name: str
    coordinates: list[tuple[float, float]]
    speed_mps: float
    dwell_seconds: float = 0.0


@dataclass(frozen=True)
class RouteStop:
    latitude: float
    longitude: float
    distance_from_start_meters: float
    dwell_seconds: float


@dataclass(frozen=True)
class _TimelineItem:
    kind: str
    start_time: float
    duration: float
    start_distance: float
    end_distance: float


def fetch_road_route(
    start: tuple[float, float],
    destination: tuple[float, float],
    timeout: float = 20.0,
) -> tuple[list[tuple[float, float]], float]:
    route = fetch_road_route_details(start, destination, timeout=timeout)
    return route.coordinates, route.distance_meters


def fetch_road_route_details(
    start: tuple[float, float],
    destination: tuple[float, float],
    timeout: float = 20.0,
) -> RoadRoute:
    start_lon_lat = f"{start[1]:.8f},{start[0]:.8f}"
    end_lon_lat = f"{destination[1]:.8f},{destination[0]:.8f}"
    params = urllib.parse.urlencode(
        {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
            "annotations": "speed",
        }
    )
    url = f"{OSRM_ROUTE_URL.format(start=start_lon_lat, end=end_lon_lat)}?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": "TetherLoc/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("code") not in (None, "Ok"):
        raise RuntimeError(data.get("message") or "Road router rejected those points.")

    routes = data.get("routes") or []
    if not routes:
        raise RuntimeError("No road route was returned for those points.")

    route = routes[0]
    raw_coordinates = route["geometry"]["coordinates"]
    coordinates = [(float(lat), float(lon)) for lon, lat in raw_coordinates]
    distance = float(route.get("distance") or path_distance(coordinates))
    if len(coordinates) < 2:
        raise RuntimeError("The route was too short to play.")

    return RoadRoute(
        coordinates=coordinates,
        distance_meters=distance,
        segment_speeds_mps=extract_annotation_speeds(route, expected_count=len(coordinates) - 1),
    )


def fetch_stop_signs_near_route(
    coordinates: list[tuple[float, float]],
    timeout: float = 25.0,
) -> list[tuple[float, float]]:
    if len(coordinates) < 2:
        return []

    south, west, north, east = route_bbox(coordinates, margin_meters=90)
    query = f"""
[out:json][timeout:{int(timeout)}];
(
  node["highway"="stop"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});
);
out body;
"""
    payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
    request = urllib.request.Request(
        OVERPASS_URL,
        data=payload,
        headers={"User-Agent": "TetherLoc/0.1", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))

    stop_signs = []
    for element in data.get("elements", []):
        if "lat" in element and "lon" in element:
            stop_signs.append((float(element["lat"]), float(element["lon"])))
    return stop_signs


def build_route_plan(
    coordinates: list[tuple[float, float]],
    mph: float,
    sample_interval_seconds: float,
    segment_speeds_mps: list[float] | None = None,
    stops: list[RouteStop] | None = None,
) -> RoutePlan:
    if mph <= 0:
        raise ValueError("MPH must be greater than zero.")
    if sample_interval_seconds < 0.5:
        raise ValueError("Smooth seconds must be at least 0.5.")

    fallback_speed_mps = mph * 0.44704
    segment_distances = path_segment_distances(coordinates)
    segment_speeds, used_auto_speed = resolve_segment_speeds(
        segment_speeds_mps,
        expected_count=len(segment_distances),
        fallback_mps=fallback_speed_mps,
    )
    sampled = sample_timed_route(
        coordinates,
        segment_distances,
        segment_speeds,
        sample_interval_seconds,
        stops or [],
    )
    total_distance = sum(segment_distances)
    total_duration = sampled[-1].elapsed_seconds if sampled else 0
    gpx_path = write_gpx(sampled)
    return RoutePlan(
        coordinates=[(point.latitude, point.longitude) for point in sampled],
        distance_meters=total_distance,
        duration_seconds=total_duration,
        gpx_path=gpx_path,
        used_auto_speed=used_auto_speed,
        stop_count=len(stops or []),
    )


def sample_route(
    coordinates: list[tuple[float, float]],
    speed_mps: float,
    sample_interval_seconds: float,
) -> list[RoutePoint]:
    if speed_mps <= 0:
        raise ValueError("Speed must be greater than zero.")
    segment_distances = path_segment_distances(coordinates)
    return sample_timed_route(
        coordinates,
        segment_distances,
        [speed_mps] * len(segment_distances),
        sample_interval_seconds,
        [],
    )


def build_flight_plan(
    origin: tuple[float, float],
    destination: tuple[float, float],
    cruise_mph: float,
    taxi_mph: float,
    sample_interval_seconds: float,
    boarding_seconds: float,
) -> RoutePlan:
    if origin == destination:
        raise ValueError("Choose two different airports.")
    if cruise_mph <= 0 or taxi_mph <= 0:
        raise ValueError("Flight and taxi speeds must be greater than zero.")
    if sample_interval_seconds < 1:
        raise ValueError("Flight smooth seconds must be at least 1.")

    bearing = bearing_degrees(origin, destination)
    total_air_distance = haversine_meters(origin, destination)
    taxi_distance = min(1600.0, max(450.0, total_air_distance * 0.01))
    climb_distance = min(16_000.0, max(4_000.0, total_air_distance * 0.08))
    approach_distance = min(18_000.0, max(5_000.0, total_air_distance * 0.10))

    origin_runway = destination_point(origin, bearing, taxi_distance)
    climb_out = destination_point(origin_runway, bearing, climb_distance)
    destination_runway = destination_point(destination, (bearing + 180) % 360, taxi_distance)
    approach_fix = destination_point(destination_runway, (bearing + 180) % 360, approach_distance)

    cruise_start = climb_out
    cruise_end = approach_fix

    taxi_speed = taxi_mph * 0.44704
    climb_speed = min(cruise_mph * 0.44704, 210 * 0.44704)
    cruise_speed = cruise_mph * 0.44704
    approach_speed = min(cruise_mph * 0.44704, 190 * 0.44704)

    stages = [
        FlightStage("Boarding", [origin], speed_mps=taxi_speed, dwell_seconds=boarding_seconds),
        FlightStage("Taxi to runway", [origin, origin_runway], speed_mps=taxi_speed),
        FlightStage("Takeoff climb", [origin_runway, climb_out], speed_mps=climb_speed),
        FlightStage("Cruise", [cruise_start, cruise_end], speed_mps=cruise_speed),
        FlightStage("Approach", [approach_fix, destination_runway], speed_mps=approach_speed),
        FlightStage("Taxi to gate", [destination_runway, destination], speed_mps=taxi_speed),
        FlightStage("Arrived", [destination], speed_mps=taxi_speed, dwell_seconds=min(boarding_seconds, 30)),
    ]

    sampled: list[RoutePoint] = []
    elapsed = 0.0
    distance = 0.0
    for stage in stages:
        if stage.dwell_seconds > 0:
            elapsed = append_dwell_samples(sampled, stage.coordinates[0], elapsed, stage.dwell_seconds, sample_interval_seconds)
            continue
        start, end = stage.coordinates[0], stage.coordinates[-1]
        segment_distance = haversine_meters(start, end)
        distance += segment_distance
        elapsed = append_flight_segment_samples(
            sampled,
            start,
            end,
            elapsed,
            max(stage.speed_mps, 0.01),
            sample_interval_seconds,
        )

    gpx_path = write_gpx(sampled)
    return RoutePlan(
        coordinates=[(point.latitude, point.longitude) for point in sampled],
        distance_meters=distance,
        duration_seconds=elapsed,
        gpx_path=gpx_path,
        used_auto_speed=False,
        stop_count=0,
    )


def append_dwell_samples(
    points: list[RoutePoint],
    coordinate: tuple[float, float],
    elapsed: float,
    duration: float,
    sample_interval_seconds: float,
) -> float:
    if not points:
        points.append(RoutePoint(coordinate[0], coordinate[1], elapsed))
    steps = max(1, int(math.ceil(duration / sample_interval_seconds)))
    for step in range(1, steps + 1):
        next_elapsed = elapsed + min(duration, step * sample_interval_seconds)
        points.append(RoutePoint(coordinate[0], coordinate[1], next_elapsed))
    return elapsed + duration


def append_flight_segment_samples(
    points: list[RoutePoint],
    start: tuple[float, float],
    end: tuple[float, float],
    elapsed: float,
    speed_mps: float,
    sample_interval_seconds: float,
) -> float:
    if not points:
        points.append(RoutePoint(start[0], start[1], elapsed))
    distance = haversine_meters(start, end)
    if distance <= 0:
        return elapsed
    duration = distance / speed_mps
    steps = max(1, int(math.ceil(duration / sample_interval_seconds)))
    if len(points) + steps > MAX_ROUTE_POINTS:
        raise ValueError("Flight would create too many points. Increase Flight smooth seconds or Flight MPH.")
    for step in range(1, steps + 1):
        ratio = min(1.0, (step * sample_interval_seconds) / duration)
        lat, lon = interpolate_great_circle(start, end, ratio)
        points.append(RoutePoint(lat, lon, elapsed + duration * ratio))
    return elapsed + duration


def sample_timed_route(
    coordinates: list[tuple[float, float]],
    segment_distances: list[float],
    segment_speeds_mps: list[float],
    sample_interval_seconds: float,
    stops: list[RouteStop],
) -> list[RoutePoint]:
    if len(coordinates) < 2:
        raise ValueError("At least two route coordinates are required.")
    if sample_interval_seconds < 0.5:
        raise ValueError("Smooth seconds must be at least 0.5.")

    total_distance = sum(segment_distances)
    if total_distance == 0:
        first = coordinates[0]
        return [RoutePoint(first[0], first[1], 0)]

    timeline = build_timeline(coordinates, segment_distances, segment_speeds_mps, stops)
    total_duration = timeline[-1].start_time + timeline[-1].duration if timeline else 0
    samples = max(2, int(math.ceil(total_duration / sample_interval_seconds)) + 1)
    if samples > MAX_ROUTE_POINTS:
        raise ValueError("Route would create too many points. Increase MPH or Smooth sec.")

    points = []
    event_index = 0
    for sample_index in range(samples):
        elapsed = min(sample_index * sample_interval_seconds, total_duration)
        while event_index < len(timeline) - 1 and elapsed > timeline[event_index].start_time + timeline[event_index].duration:
            event_index += 1
        target_distance = timeline_distance_at(timeline[event_index], elapsed)
        lat, lon = interpolate_along_path(coordinates, segment_distances, target_distance)
        points.append(RoutePoint(lat, lon, elapsed))

    end_lat, end_lon = coordinates[-1]
    if points[-1].latitude != end_lat or points[-1].longitude != end_lon:
        points.append(RoutePoint(end_lat, end_lon, total_duration))
    return points


def build_timeline(
    coordinates: list[tuple[float, float]],
    segment_distances: list[float],
    segment_speeds_mps: list[float],
    stops: list[RouteStop],
) -> list[_TimelineItem]:
    cumulative = cumulative_distances(segment_distances)
    total_distance = cumulative[-1]
    usable_stops = [
        stop
        for stop in sorted(stops, key=lambda item: item.distance_from_start_meters)
        if 0 < stop.distance_from_start_meters < total_distance and stop.dwell_seconds > 0
    ]

    timeline: list[_TimelineItem] = []
    elapsed = 0.0
    current_distance = 0.0
    for stop in usable_stops:
        elapsed = append_movement_timeline(
            timeline,
            cumulative,
            segment_speeds_mps,
            current_distance,
            stop.distance_from_start_meters,
            elapsed,
        )
        timeline.append(
            _TimelineItem(
                kind="stop",
                start_time=elapsed,
                duration=stop.dwell_seconds,
                start_distance=stop.distance_from_start_meters,
                end_distance=stop.distance_from_start_meters,
            )
        )
        elapsed += stop.dwell_seconds
        current_distance = stop.distance_from_start_meters

    append_movement_timeline(timeline, cumulative, segment_speeds_mps, current_distance, total_distance, elapsed)
    return timeline


def append_movement_timeline(
    timeline: list[_TimelineItem],
    cumulative: list[float],
    segment_speeds_mps: list[float],
    start_distance: float,
    end_distance: float,
    elapsed: float,
) -> float:
    current_distance = start_distance
    while current_distance < end_distance:
        index = segment_index_for_distance(cumulative, current_distance)
        segment_end = min(end_distance, cumulative[index + 1])
        distance = segment_end - current_distance
        if distance <= 0:
            break
        speed = max(segment_speeds_mps[index], 0.01)
        duration = distance / speed
        timeline.append(
            _TimelineItem(
                kind="move",
                start_time=elapsed,
                duration=duration,
                start_distance=current_distance,
                end_distance=segment_end,
            )
        )
        elapsed += duration
        current_distance = segment_end
    return elapsed


def timeline_distance_at(event: _TimelineItem, elapsed: float) -> float:
    if event.kind == "stop" or event.duration <= 0:
        return event.start_distance
    ratio = min(1.0, max(0.0, (elapsed - event.start_time) / event.duration))
    return event.start_distance + (event.end_distance - event.start_distance) * ratio


def segment_index_for_distance(cumulative: list[float], distance: float) -> int:
    index = bisect_right(cumulative, distance) - 1
    return min(max(index, 0), len(cumulative) - 2)


def resolve_segment_speeds(
    segment_speeds_mps: list[float] | None,
    expected_count: int,
    fallback_mps: float,
) -> tuple[list[float], bool]:
    if expected_count <= 0:
        return [], False
    if not segment_speeds_mps or len(segment_speeds_mps) != expected_count:
        return [fallback_mps] * expected_count, False

    speeds = []
    for raw_speed in segment_speeds_mps:
        try:
            speed = float(raw_speed)
        except (TypeError, ValueError):
            speed = fallback_mps
        if not math.isfinite(speed) or speed <= 0:
            speed = fallback_mps
        speeds.append(min(MAX_AUTO_SPEED_MPS, max(MIN_AUTO_SPEED_MPS, speed)))
    return speeds, True


def extract_annotation_speeds(route: dict, expected_count: int) -> list[float]:
    legs = route.get("legs") or []
    speeds = []
    for leg in legs:
        annotation = leg.get("annotation") or {}
        speeds.extend(annotation.get("speed") or [])
    if len(speeds) != expected_count:
        return []
    try:
        return [float(speed) for speed in speeds]
    except (TypeError, ValueError):
        return []


def match_stop_signs_to_route(
    coordinates: list[tuple[float, float]],
    stop_signs: list[tuple[float, float]],
    dwell_seconds: float,
    threshold_meters: float = 18.0,
) -> list[RouteStop]:
    if len(coordinates) < 2 or not stop_signs or dwell_seconds <= 0:
        return []

    segment_distances = path_segment_distances(coordinates)
    cumulative = cumulative_distances(segment_distances)
    candidates = []
    for stop in stop_signs:
        best_distance = math.inf
        best_position = 0.0
        best_coordinate = coordinates[0]
        for index, segment_distance in enumerate(segment_distances):
            distance_to_segment, ratio = point_to_segment_distance_meters(stop, coordinates[index], coordinates[index + 1])
            if distance_to_segment < best_distance:
                best_distance = distance_to_segment
                best_position = cumulative[index] + segment_distance * ratio
                best_coordinate = (
                    coordinates[index][0] + (coordinates[index + 1][0] - coordinates[index][0]) * ratio,
                    coordinates[index][1] + (coordinates[index + 1][1] - coordinates[index][1]) * ratio,
                )
        if best_distance <= threshold_meters:
            candidates.append((best_position, best_coordinate))

    candidates.sort(key=lambda item: item[0])
    stops = []
    last_position = -math.inf
    for position, coordinate in candidates:
        if position - last_position < 25:
            continue
        stops.append(RouteStop(coordinate[0], coordinate[1], position, dwell_seconds))
        last_position = position
    return stops


def interpolate_along_path(
    coordinates: list[tuple[float, float]],
    segment_distances: list[float],
    target_distance: float,
) -> tuple[float, float]:
    travelled = 0.0
    for index, segment_distance in enumerate(segment_distances):
        if travelled + segment_distance >= target_distance:
            start = coordinates[index]
            end = coordinates[index + 1]
            ratio = 0 if segment_distance == 0 else (target_distance - travelled) / segment_distance
            return (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
        travelled += segment_distance
    return coordinates[-1]


def route_bbox(coordinates: list[tuple[float, float]], margin_meters: float) -> tuple[float, float, float, float]:
    latitudes = [coordinate[0] for coordinate in coordinates]
    longitudes = [coordinate[1] for coordinate in coordinates]
    mid_lat = math.radians((min(latitudes) + max(latitudes)) / 2)
    lat_margin = math.degrees(margin_meters / EARTH_RADIUS_METERS)
    lon_margin = math.degrees(margin_meters / max(EARTH_RADIUS_METERS * math.cos(mid_lat), 1))
    return (
        min(latitudes) - lat_margin,
        min(longitudes) - lon_margin,
        max(latitudes) + lat_margin,
        max(longitudes) + lon_margin,
    )


def point_to_segment_distance_meters(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    origin_lat = math.radians(point[0])
    px, py = project_local(point, origin_lat)
    ax, ay = project_local(start, origin_lat)
    bx, by = project_local(end, origin_lat)
    dx = bx - ax
    dy = by - ay
    denominator = dx * dx + dy * dy
    ratio = 0.0 if denominator == 0 else ((px - ax) * dx + (py - ay) * dy) / denominator
    ratio = min(1.0, max(0.0, ratio))
    closest_x = ax + dx * ratio
    closest_y = ay + dy * ratio
    return math.hypot(px - closest_x, py - closest_y), ratio


def project_local(coordinate: tuple[float, float], origin_lat: float) -> tuple[float, float]:
    lat, lon = coordinate
    return (
        math.radians(lon) * EARTH_RADIUS_METERS * math.cos(origin_lat),
        math.radians(lat) * EARTH_RADIUS_METERS,
    )


def write_gpx(points: list[RoutePoint]) -> Path:
    gpx = ET.Element("gpx", attrib={"version": "1.1", "creator": "TetherLoc"})
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = "TetherLoc Roadtrip"
    segment = ET.SubElement(trk, "trkseg")
    start_time = datetime.now(timezone.utc).replace(microsecond=0)

    for point in points:
        trkpt = ET.SubElement(
            segment,
            "trkpt",
            attrib={"lat": f"{point.latitude:.8f}", "lon": f"{point.longitude:.8f}"},
        )
        timestamp = start_time + timedelta(seconds=point.elapsed_seconds)
        ET.SubElement(trkpt, "time").text = timestamp.isoformat().replace("+00:00", "Z")

    directory = Path(tempfile.gettempdir()) / "tetherloc"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"roadtrip-{int(start_time.timestamp())}.gpx"
    ET.ElementTree(gpx).write(path, encoding="utf-8", xml_declaration=True)
    return path


def path_distance(coordinates: list[tuple[float, float]]) -> float:
    return sum(path_segment_distances(coordinates))


def path_segment_distances(coordinates: list[tuple[float, float]]) -> list[float]:
    return [haversine_meters(coordinates[index], coordinates[index + 1]) for index in range(len(coordinates) - 1)]


def cumulative_distances(segment_distances: list[float]) -> list[float]:
    distances = [0.0]
    for distance in segment_distances:
        distances.append(distances[-1] + distance)
    return distances


def haversine_meters(start: tuple[float, float], end: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(start[0]), math.radians(start[1])
    lat2, lon2 = math.radians(end[0]), math.radians(end[1])
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_degrees(start: tuple[float, float], end: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(start[0]), math.radians(end[0])
    d_lon = math.radians(end[1] - start[1])
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination_point(start: tuple[float, float], bearing: float, distance_meters: float) -> tuple[float, float]:
    lat1 = math.radians(start[0])
    lon1 = math.radians(start[1])
    angular_distance = distance_meters / EARTH_RADIUS_METERS
    bearing_rad = math.radians(bearing)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing_rad)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), normalize_longitude(math.degrees(lon2))


def interpolate_great_circle(
    start: tuple[float, float],
    end: tuple[float, float],
    ratio: float,
) -> tuple[float, float]:
    ratio = min(1.0, max(0.0, ratio))
    lat1, lon1 = math.radians(start[0]), math.radians(start[1])
    lat2, lon2 = math.radians(end[0]), math.radians(end[1])
    angular_distance = haversine_meters(start, end) / EARTH_RADIUS_METERS
    if angular_distance == 0:
        return start
    sin_distance = math.sin(angular_distance)
    a = math.sin((1 - ratio) * angular_distance) / sin_distance
    b = math.sin(ratio * angular_distance) / sin_distance
    x = a * math.cos(lat1) * math.cos(lon1) + b * math.cos(lat2) * math.cos(lon2)
    y = a * math.cos(lat1) * math.sin(lon1) + b * math.cos(lat2) * math.sin(lon2)
    z = a * math.sin(lat1) + b * math.sin(lat2)
    lat = math.atan2(z, math.sqrt(x * x + y * y))
    lon = math.atan2(y, x)
    return math.degrees(lat), normalize_longitude(math.degrees(lon))


def normalize_longitude(longitude: float) -> float:
    return ((longitude + 180) % 360) - 180
