import pathlib
import tempfile
import unittest

from deploy.render_cloud_run import render_service


class DeployConfigTests(unittest.TestCase):
    def test_cloud_run_sidecar_contract(self):
        text = pathlib.Path("deploy/cloud-run-service.yaml").read_text(encoding="utf-8")
        for value in (
            "gotenberg/gotenberg:8.34.0-libreoffice",
            'run.googleapis.com/container-dependencies: \'{"web":["gotenberg"]}\'',
            "containerConcurrency: 1",
            "timeoutSeconds: 900",
            "path: /health",
            "port: 3000",
            "memory: 1Gi",
            "memory: 2Gi",
        ):
            self.assertIn(value, text)

    def test_renderer_replaces_only_web_image_token(self):
        rendered = render_service("asia-south1-docker.pkg.dev/example/app/web@sha256:abc")
        self.assertNotIn("__WEB_IMAGE__", rendered)
        self.assertIn("web@sha256:abc", rendered)
        self.assertIn("gotenberg/gotenberg:8.34.0-libreoffice", rendered)


if __name__ == "__main__":
    unittest.main()
