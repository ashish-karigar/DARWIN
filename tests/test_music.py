from unittest.mock import patch

from app.integrations.music import apple_music
from app.tools import music


def test_stop_is_normalized_to_pause():
    assert music._normalized_playback_action("stop") == "pause"


def test_other_actions_are_unchanged():
    for action in ("pause", "resume", "next", "previous"):
        assert music._normalized_playback_action(action) == action


@patch("app.integrations.music.apple_music.subprocess.run")
def test_stop_pauses_apple_music(run):
    run.return_value.returncode = 0

    result = apple_music.control("stop")

    command = run.call_args.args[0]

    assert 'tell application "Music" to pause' in command
    assert result == "Apple Music playback paused."


@patch("app.tools.music.spotify.play")
@patch("app.tools.music.spotify.is_authorized", return_value=True)
@patch("app.tools.music.spotify.is_configured", return_value=True)
def test_auto_prefers_spotify(
    _configured,
    _authorized,
    spotify_play,
):
    spotify_play.return_value = "Playing on Spotify."

    with patch.dict(
        "os.environ",
        {"DEFAULT_MUSIC_PROVIDER": "spotify"},
    ):
        result = music._play_with_fallback(
            "Back In Black",
            "AC/DC",
            "auto",
        )

    assert result == "Playing on Spotify."
    spotify_play.assert_called_once_with("Back In Black", "AC/DC")


@patch("app.tools.music.apple_music.play")
@patch("app.tools.music.apple_music.is_available", return_value=True)
@patch("app.tools.music.spotify.play")
@patch("app.tools.music.spotify.is_authorized", return_value=True)
@patch("app.tools.music.spotify.is_configured", return_value=True)
def test_auto_falls_back_to_apple_music(
    _configured,
    _authorized,
    spotify_play,
    _apple_available,
    apple_play,
):
    spotify_play.side_effect = music.spotify.SpotifyPlaybackError(
        "Spotify unavailable"
    )
    apple_play.return_value = "Playing in Apple Music."

    with patch.dict(
        "os.environ",
        {"DEFAULT_MUSIC_PROVIDER": "spotify"},
    ):
        result = music._play_with_fallback(
            "Back In Black",
            "AC/DC",
            "auto",
        )

    assert result == "Playing in Apple Music."
    apple_play.assert_called_once_with("Back In Black", "AC/DC")