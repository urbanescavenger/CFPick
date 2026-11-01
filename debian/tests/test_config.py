import os
import tempfile
import unittest
from pathlib import Path

from cfspeedtest import config, paths


class NormalizeTests(unittest.TestCase):
    def test_defaults(self):
        cfg = config.normalize({})
        self.assertEqual(cfg["ip_source"], "builtin_ipv4")
        self.assertEqual(cfg["probes"], 3)
        self.assertEqual(cfg["download_count"], 5)
        self.assertEqual(len(cfg["ip_lists"]), 5)
        self.assertTrue(cfg["ip_lists"][0]["enabled"])
        self.assertFalse(cfg["ip_lists"][1]["enabled"])
        self.assertEqual(cfg["web"]["port"], 8787)

    def test_clamps(self):
        cfg = config.normalize({
            "probes": 99,
            "download_count": 0,
            "test_count": 0,
            "loss_max": 5,
            "web": {"port": 99999},
        })
        self.assertEqual(cfg["probes"], 5)
        self.assertEqual(cfg["download_count"], 1)
        self.assertEqual(cfg["test_count"], 1)
        self.assertEqual(cfg["loss_max"], 1.0)
        self.assertEqual(cfg["web"]["port"], 65535)

    def test_node_names_are_unique(self):
        cfg = config.normalize({"nodes": [
            {"name": "same", "link": "vless://a@b:443#x"},
            {"name": "same", "link": "vless://c@d:443#y"},
            {"name": "", "link": "vless://e@f:443#z"},
            {"name": "no-link", "link": ""},
        ]})
        names = [node["name"] for node in cfg["nodes"]]
        self.assertEqual(names, ["same", "same-2", "node3"])

    def test_invalid_cron_falls_back(self):
        cfg = config.normalize({"schedule": {"custom_cron": "bad"}})
        self.assertEqual(cfg["schedule"]["custom_cron"], "0 3 * * *")

    def test_regions_normalized(self):
        cfg = config.normalize({"ip_lists": [
            {"enabled": True, "regions": "jp, sg  jp"},
        ]})
        self.assertEqual(cfg["ip_lists"][0]["regions"], ["JP", "SG"])

    def test_core_type(self):
        self.assertEqual(config.normalize({})["core"]["type"], "mihomo")
        self.assertEqual(config.normalize({"core": {"type": "xray"}})["core"]["type"], "xray")
        self.assertEqual(config.normalize({"core": {"type": "bogus"}})["core"]["type"], "mihomo")

    def test_core_paths(self):
        cfg = config.normalize({"core": {"paths": {"mihomo": "/a", "xray": "/b"}}})
        self.assertEqual(cfg["core"]["paths"], {"mihomo": "/a", "xray": "/b"})
        # Old single-path config migrates to the selected core only.
        cfg = config.normalize({"core": {"type": "xray", "path": "/opt/xray"}})
        self.assertEqual(cfg["core"]["paths"]["xray"], "/opt/xray")
        self.assertEqual(cfg["core"]["paths"]["mihomo"], "")


class SaveLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._config_dir = paths.CONFIG_DIR
        self._config_file = paths.CONFIG_FILE
        paths.CONFIG_DIR = self.root
        paths.CONFIG_FILE = self.root / "config.json"

    def tearDown(self):
        paths.CONFIG_DIR = self._config_dir
        paths.CONFIG_FILE = self._config_file
        self.tmp.cleanup()

    def test_roundtrip_and_mode(self):
        cfg = config.normalize({"nodes": [{"name": "n", "link": "vless://u@h:443#n"}]})
        config.save(cfg)
        loaded = config.load()
        self.assertEqual(loaded["nodes"][0]["name"], "n")
        if os.name != "nt":
            mode = (self.root / "config.json").stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_load_creates_file(self):
        loaded = config.load()
        self.assertTrue((self.root / "config.json").exists())
        self.assertEqual(loaded["ip_source"], "builtin_ipv4")


if __name__ == "__main__":
    unittest.main()
