import unittest
from pathlib import Path

from ios_geo_spoofer.backend import (
    Device,
    TunnelInfo,
    build_dvt_clear_args,
    build_dvt_play_args,
    build_dvt_set_args,
    build_legacy_play_args,
    build_legacy_set_args,
    extract_json_array,
    format_coord,
    format_latitude,
    format_longitude,
    parse_rsd_from_text,
)


class BackendTests(unittest.TestCase):
    def test_parse_rsd_option(self):
        info = parse_rsd_from_text("Use the follow connection option:\n--rsd fd03:daf1::1 56870")
        self.assertEqual(info, TunnelInfo("fd03:daf1::1", 56870))

    def test_parse_rsd_lines(self):
        info = parse_rsd_from_text("RSD Address: fdca:4c1:f20f::1\nRSD Port: 65456")
        self.assertEqual(info, TunnelInfo("fdca:4c1:f20f::1", 65456))

    def test_extract_json_array_with_logs(self):
        output = 'INFO before\n[{"DeviceName":"iPhone","ProductVersion":"18.1"}]\n'
        self.assertEqual(extract_json_array(output), [{"DeviceName": "iPhone", "ProductVersion": "18.1"}])

    def test_build_dvt_set_args(self):
        args = build_dvt_set_args(TunnelInfo("fd03::1", 12345), "37.3349", "-122.009")
        self.assertEqual(
            args,
            [
                "developer",
                "dvt",
                "simulate-location",
                "set",
                "--rsd",
                "fd03::1",
                "12345",
                "--",
                "37.3349",
                "-122.009",
            ],
        )

    def test_build_dvt_clear_args(self):
        self.assertEqual(
            build_dvt_clear_args(TunnelInfo("fd03::1", 12345)),
            ["developer", "dvt", "simulate-location", "clear", "--rsd", "fd03::1", "12345"],
        )

    def test_build_dvt_play_args(self):
        self.assertEqual(
            build_dvt_play_args(TunnelInfo("fd03::1", 12345), Path("route.gpx")),
            [
                "developer",
                "dvt",
                "simulate-location",
                "play",
                "--rsd",
                "fd03::1",
                "12345",
                "--",
                "route.gpx",
            ],
        )

    def test_build_legacy_set_args(self):
        device = Device("abc", "Phone", "16.7", "iPhone", "USB", {})
        self.assertEqual(
            build_legacy_set_args(device, "1", "2"),
            ["developer", "simulate-location", "set", "--udid", "abc", "--", "1", "2"],
        )

    def test_build_legacy_play_args(self):
        device = Device("abc", "Phone", "16.7", "iPhone", "USB", {})
        self.assertEqual(
            build_legacy_play_args(device, Path("route.gpx")),
            ["developer", "simulate-location", "play", "--udid", "abc", "--", "route.gpx"],
        )

    def test_format_coord(self):
        self.assertEqual(format_coord(37.33490000), "37.3349")
        self.assertEqual(format_coord("-122.009000"), "-122.009")

    def test_format_coord_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            format_coord(181)

    def test_latitude_and_longitude_ranges(self):
        with self.assertRaises(ValueError):
            format_latitude(91)
        self.assertEqual(format_longitude(179.5), "179.5")


if __name__ == "__main__":
    unittest.main()
