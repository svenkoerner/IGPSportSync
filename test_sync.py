#!/usr/bin/env python3
import unittest
from unittest.mock import patch, MagicMock
import os
import tempfile
from datetime import datetime

# Import methods from sync
from sync import (
    semicircles_to_degrees,
    sanitize_filename,
    extract_activity_id_from_response,
    generate_tour_name,
    extract_gpx_data,
    IGPSPORTClient
)

class TestSyncApp(unittest.TestCase):

    def test_semicircles_to_degrees(self):
        # 180 degrees in semicircles is 2**31
        self.assertAlmostEqual(semicircles_to_degrees(2147483648), 180.0)
        self.assertAlmostEqual(semicircles_to_degrees(1073741824), 90.0)
        self.assertAlmostEqual(semicircles_to_degrees(-1073741824), -90.0)
        self.assertIsNone(semicircles_to_degrees(None))

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("Ride from Munich to Freising"), "Ride_from_Munich_to_Freising")
        self.assertEqual(sanitize_filename("Ride in Munich!!!"), "Ride_in_Munich")
        self.assertEqual(sanitize_filename("A/B-C_D"), "AB-C_D")
        self.assertEqual(sanitize_filename("  spaces   and  dots.. "), "spaces_and_dots")

    def test_extract_activity_id_from_response(self):
        # Test expected structure
        response = {
            'detailedImportResult': {
                'successes': [
                    {'internalId': 12345678, 'externalId': 'abc-123'}
                ]
            }
        }
        self.assertEqual(extract_activity_id_from_response(response), 12345678)
        
        # Test invalid or missing structure
        self.assertIsNone(extract_activity_id_from_response(None))
        self.assertIsNone(extract_activity_id_from_response({}))
        self.assertIsNone(extract_activity_id_from_response("string response"))

    @patch('sync.reverse_geocode')
    def test_generate_tour_name(self, mock_geocode):
        # Case 1: Start and end same
        mock_geocode.side_effect = lambda lat, lon: "Munich"
        name = generate_tour_name((48.1, 11.5), (48.1, 11.5))
        self.assertEqual(name, "Ride in Munich")

        # Case 2: Start and end different
        mock_geocode.side_effect = lambda lat, lon: "Munich" if lat == 48.1 else "Freising"
        name = generate_tour_name((48.1, 11.5), (48.4, 11.7))
        self.assertEqual(name, "Ride from Munich to Freising")

        # Case 3: Only start known
        mock_geocode.side_effect = lambda lat, lon: "Munich" if lat == 48.1 else None
        name = generate_tour_name((48.1, 11.5), (48.4, 11.7))
        self.assertEqual(name, "Ride from Munich")

        # Case 4: None known
        mock_geocode.side_effect = lambda lat, lon: None
        name = generate_tour_name((48.1, 11.5), (48.4, 11.7))
        self.assertEqual(name, "Bike Ride")

    def test_extract_gpx_data(self):
        gpx_content = """<?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" creator="Mock GPX Creator" xmlns="http://www.topografix.com/GPX/1/1">
          <metadata>
            <time>2026-05-24T12:00:00Z</time>
          </metadata>
          <trk>
            <name>Test Track</name>
            <trkseg>
              <trkpt lat="48.137" lon="11.575">
                <time>2026-05-24T12:00:05Z</time>
              </trkpt>
              <trkpt lat="48.140" lon="11.580">
                <time>2026-05-24T12:05:00Z</time>
              </trkpt>
              <trkpt lat="48.200" lon="11.600">
                <time>2026-05-24T12:10:00Z</time>
              </trkpt>
            </trkseg>
          </trk>
        </gpx>
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gpx', delete=False) as f:
            f.write(gpx_content)
            temp_path = f.name
            
        try:
            start_coord, end_coord, start_time = extract_gpx_data(temp_path)
            self.assertIsNotNone(start_coord)
            self.assertIsNotNone(end_coord)
            self.assertIsNotNone(start_time)
            self.assertAlmostEqual(start_coord[0], 48.137)
            self.assertAlmostEqual(start_coord[1], 11.575)
            self.assertAlmostEqual(end_coord[0], 48.200)
            self.assertAlmostEqual(end_coord[1], 11.600)
            self.assertEqual(start_time.year, 2026)
            self.assertEqual(start_time.month, 5)
            self.assertEqual(start_time.day, 24)
            self.assertEqual(start_time.hour, 12)
            self.assertEqual(start_time.minute, 0)
            self.assertEqual(start_time.second, 5)
        finally:
            os.remove(temp_path)

    @patch('sync.requests.Session')
    def test_igpsport_client_login_success(self, mock_session):
        session_instance = mock_session.return_value
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "access_token": "mock_jwt_token"
            }
        }
        session_instance.post.return_value = mock_response

        client = IGPSPORTClient("test_user", "test_pass")
        self.assertTrue(client.login())
        self.assertEqual(client.token, "mock_jwt_token")
        session_instance.post.assert_called_once_with(
            "https://prod.zh.igpsport.com/service/auth/account/login",
            json={"appId": "igpsport-web", "username": "test_user", "password": "test_pass"}
        )

    @patch('sync.requests.Session')
    def test_igpsport_client_login_failure(self, mock_session):
        session_instance = mock_session.return_value
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "code": 10001,
            "message": "Wrong password"
        }
        session_instance.post.return_value = mock_response

        client = IGPSPORTClient("test_user", "test_pass")
        with self.assertRaises(Exception) as context:
            client.login()
        self.assertIn("Login failed: Wrong password", str(context.exception))

    @patch('sync.requests.Session')
    def test_igpsport_client_get_activities(self, mock_session):
        session_instance = mock_session.return_value
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "rows": [
                    {"rideId": 12345, "title": "Tour 1"},
                    {"rideId": 67890, "title": "Tour 2"}
                ]
            }
        }
        session_instance.get.return_value = mock_response

        client = IGPSPORTClient("test_user", "test_pass")
        client.token = "mock_token"
        res = client.get_activities(page_no=1, page_size=20)
        self.assertEqual(res["code"], 0)
        self.assertEqual(len(res["data"]["rows"]), 2)
        session_instance.get.assert_called_once_with(
            "https://prod.zh.igpsport.com/service/web-gateway/web-analyze/activity/queryMyActivity",
            params={"pageNo": "1", "pageSize": "20", "sort": "1", "reqType": "0"}
        )

    @patch('sync.requests.Session')
    def test_igpsport_client_delete_activity_success(self, mock_session):
        session_instance = mock_session.return_value
        
        mock_response_fail = MagicMock()
        mock_response_fail.status_code = 404
        
        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {"code": 0}
        
        session_instance.post.side_effect = [mock_response_fail, mock_response_success]
        
        client = IGPSPORTClient("test_user", "test_pass")
        client.token = "mock_token"
        
        self.assertTrue(client.delete_activity(12345))
        self.assertEqual(session_instance.post.call_count, 2)


if __name__ == '__main__':
    unittest.main()
