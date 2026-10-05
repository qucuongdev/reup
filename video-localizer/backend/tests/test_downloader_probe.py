import pytest

from app.core.config import Settings
from app.core.process import JobLog, PipelineError, ProcessRunner
from app.services.downloader.ytdlp import YtDlpDownloader, source_metadata, validate_url
from app.services.probe import media_metadata


@pytest.mark.parametrize(
    "url", ["file:///x", "ftp://example.org/x", "https://user:pw@host/x", "--exec", "https://"]
)
def test_bad_url(url):
    with pytest.raises(PipelineError):
        validate_url(url)


def test_download_command_preserves_url_as_argument(tmp_path):
    url = "https://example.org/video?v=1&x=2"
    runner = ProcessRunner(JobLog(tmp_path / "logs"))
    downloader = YtDlpDownloader(Settings(_env_file=None), runner)
    command = downloader.build_command(url, tmp_path)
    assert command[-2:] == ["--", url]
    assert "--no-playlist" in command
    assert "--ignore-config" in command
    assert command[command.index("--match-filter") + 1].startswith("duration <=? ")
    assert "--recode-video" in command
    assert str(tmp_path / "source.%(ext)s") in command


def test_partial_source_metadata():
    result = source_metadata({"title": "Video"}, "https://example.org/x")
    assert result["title"] == "Video"
    assert result["duration"] is None
    assert result["source_url"] == "https://example.org/x"


def test_probe_metadata():
    result = media_metadata(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                },
                {"codec_type": "audio"},
            ],
            "format": {"duration": "12.3"},
        }
    )
    assert result["fps"] == pytest.approx(29.97, abs=0.01)
    assert result["duration"] == 12.3
    assert result["has_audio"] is True
    with pytest.raises(PipelineError):
        media_metadata({"streams": [{"codec_type": "audio"}]})
