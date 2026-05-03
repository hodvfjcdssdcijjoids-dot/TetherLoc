import unittest

from ios_geo_spoofer.backend import (
    clean_command_output,
    format_location_command_error,
    is_developer_image_mount_failure,
    parse_bool_output,
)
from ios_geo_spoofer.routing import (
    RouteStop,
    build_flight_plan,
    build_route_plan,
    haversine_meters,
    match_stop_signs_to_route,
    sample_route,
)


class RoutingTests(unittest.TestCase):
    def test_clean_command_output_strips_ansi(self):
        output = clean_command_output("\x1b[32mOK\x1b[0m\r\n\x1b[31mERROR\x1b[0m")
        self.assertEqual(output, "OK\nERROR")

    def test_developer_service_error_is_friendly(self):
        output = "ERROR Failed to start service. Make sure Developer Mode is enabled."
        message = format_location_command_error(output, "failed")
        self.assertIn("TetherLoc could not start the iOS developer location service", message)
        self.assertIn("Developer Mode", message)

    def test_developer_image_mount_failure_detects_logged_error(self):
        output = "ERROR Unable to find the correct DeveloperDiskImage"
        self.assertTrue(is_developer_image_mount_failure(output))

    def test_parse_bool_output_uses_last_json_bool_line(self):
        self.assertTrue(parse_bool_output("Running command\ntrue"))
        self.assertFalse(parse_bool_output("Running command\nfalse"))
        self.assertIsNone(parse_bool_output("Running command\nunknown"))

    def test_haversine_distance(self):
        meters = haversine_meters((37.3349, -122.0090), (37.7749, -122.4194))
        self.assertGreater(meters, 60_000)
        self.assertLess(meters, 80_000)

    def test_sample_route_adds_start_and_end(self):
        route = [(37.0, -122.0), (37.01, -122.0)]
        points = sample_route(route, speed_mps=10, sample_interval_seconds=10)
        self.assertEqual((points[0].latitude, points[0].longitude), route[0])
        self.assertEqual((points[-1].latitude, points[-1].longitude), route[-1])
        self.assertGreater(len(points), 2)

    def test_build_route_plan_writes_gpx(self):
        route = [(37.0, -122.0), (37.001, -122.0), (37.002, -122.0)]
        plan = build_route_plan(route, mph=30, sample_interval_seconds=5)
        self.assertTrue(plan.gpx_path.exists())
        self.assertGreater(plan.distance_meters, 100)
        self.assertGreater(plan.duration_seconds, 1)

    def test_fractional_interval_creates_dense_points(self):
        route = [(37.0, -122.0), (37.001, -122.0)]
        half_second_points = sample_route(route, speed_mps=10, sample_interval_seconds=0.5)
        one_second_points = sample_route(route, speed_mps=10, sample_interval_seconds=1)
        self.assertGreater(len(half_second_points), len(one_second_points))

    def test_auto_segment_speeds_change_duration(self):
        route = [(37.0, -122.0), (37.001, -122.0), (37.002, -122.0)]
        constant = build_route_plan(route, mph=30, sample_interval_seconds=1)
        automatic = build_route_plan(route, mph=30, sample_interval_seconds=1, segment_speeds_mps=[5, 5])
        self.assertTrue(automatic.used_auto_speed)
        self.assertGreater(automatic.duration_seconds, constant.duration_seconds)

    def test_stop_sign_pause_adds_duration(self):
        route = [(37.0, -122.0), (37.001, -122.0)]
        distance = haversine_meters(route[0], route[1])
        stop = RouteStop(37.0005, -122.0, distance / 2, 3)
        without_stop = build_route_plan(route, mph=20, sample_interval_seconds=1)
        with_stop = build_route_plan(route, mph=20, sample_interval_seconds=1, stops=[stop])
        self.assertGreaterEqual(with_stop.duration_seconds, without_stop.duration_seconds + 3)

    def test_match_stop_signs_to_route_filters_nearby_points(self):
        route = [(37.0, -122.0), (37.001, -122.0)]
        stops = match_stop_signs_to_route(route, [(37.0005, -122.0), (37.0005, -122.01)], dwell_seconds=3)
        self.assertEqual(len(stops), 1)

    def test_build_flight_plan_writes_gpx(self):
        sfo = (37.6213, -122.3790)
        lax = (33.9416, -118.4085)
        plan = build_flight_plan(sfo, lax, cruise_mph=480, taxi_mph=18, sample_interval_seconds=10, boarding_seconds=20)
        self.assertTrue(plan.gpx_path.exists())
        self.assertGreater(plan.distance_meters, 500_000)
        self.assertGreater(plan.duration_seconds, 1000)
        self.assertEqual(plan.coordinates[0], sfo)
        self.assertEqual(plan.coordinates[-1], lax)


if __name__ == "__main__":
    unittest.main()
