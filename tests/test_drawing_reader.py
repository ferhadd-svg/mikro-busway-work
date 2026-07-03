import unittest

from app.services.drawing_reader import _parse_json_object


class DrawingReaderTests(unittest.TestCase):
    def test_parses_plain_json(self):
        self.assertEqual(_parse_json_object('{"runs": []}'), {"runs": []})

    def test_parses_fenced_json(self):
        fence = chr(96) * 3
        value = _parse_json_object(f'{fence}json\n{{"runs": []}}\n{fence}')
        self.assertEqual(value, {"runs": []})

    def test_rejects_non_json(self):
        with self.assertRaises(ValueError):
            _parse_json_object("not json")


if __name__ == "__main__":
    unittest.main()
