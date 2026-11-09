"""Unit tests for resilient Lambda image uploads."""

import subprocess
import unittest
from unittest.mock import patch

from backend import build_agent_image


IMAGE_URI = (
    "123456789012.dkr.ecr.us-east-1.amazonaws.com/sidechart-classifier:test"
)


class PushImageTests(unittest.TestCase):
    @patch.object(build_agent_image.time, "sleep")
    @patch.object(build_agent_image, "run")
    @patch.object(build_agent_image, "ecr_image_exists")
    def test_retries_a_transient_push_failure(
        self,
        image_exists,
        run,
        sleep,
    ) -> None:
        image_exists.side_effect = [False, False, False]
        run.side_effect = [
            "password",
            "unix:///tmp/docker.sock",
            "",
            subprocess.CalledProcessError(1, ["docker", "push"]),
            "",
        ]

        build_agent_image.push_image(IMAGE_URI, "us-east-1")

        sleep.assert_called_once_with(2)
        self.assertEqual(run.call_count, 5)

    @patch.object(build_agent_image, "run")
    @patch.object(build_agent_image, "ecr_image_exists", return_value=True)
    def test_skips_an_existing_immutable_tag(self, _image_exists, run) -> None:
        build_agent_image.push_image(IMAGE_URI, "us-east-1")

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
