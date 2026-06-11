"""Per-candidate downloads: a combined multitrack MIDI + a WAV, both as attachments.

The artifacts already exist on the volume; these endpoints make them download cleanly
(cross-origin browsers ignore the <a download> attribute, so the server must send
Content-Disposition: attachment). The MIDI is re-exported from the stored arrangement
as a single DAW-ready multitrack file rather than the five per-part stems.
"""

from __future__ import annotations

import struct

import pytest


def test_combined_midi_bytes_is_valid_multitrack():
    from rezn_ai.music.midi import combined_midi_bytes

    arrangement = {
        "identity": {"tempo": 120.0},
        "parts": {
            "bass": [{"start": 0.0, "duration": 1.0, "pitch": 40, "velocity": 90}],
            "drums": [{"start": 0.0, "duration": 0.5, "pitch": 36, "velocity": 100}],
            "lead": [],  # empty part is skipped
        },
    }
    data = combined_midi_bytes(arrangement)

    assert data[:4] == b"MThd"
    fmt, ntracks, ticks = struct.unpack(">HHH", data[8:14])
    assert fmt == 1
    assert ntracks == 3  # 1 tempo track + 2 non-empty parts (lead skipped)
    assert data.count(b"MTrk") == 3  # header count matches actual chunks


def _start_one(client) -> dict:
    res = client.post("/api/batches", json={"brief": {"prompt": "dark techno", "candidate_count": 1}})
    assert res.status_code == 200, res.text
    return res.json()["candidates"][0]


def test_midi_endpoint_returns_combined_attachment(client):
    cand = _start_one(client)
    r = client.get(f"/api/candidates/{cand['candidate_id']}/midi")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("audio/midi")
    assert "attachment" in r.headers.get("content-disposition", "").lower()
    assert r.content[:4] == b"MThd"  # a real Standard MIDI File


def test_audio_endpoint_returns_wav_attachment(client):
    cand = _start_one(client)
    r = client.get(f"/api/candidates/{cand['candidate_id']}/audio")
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers.get("content-disposition", "").lower()
    assert r.content[:4] == b"RIFF"  # WAV container


def test_download_endpoints_404_for_unknown_candidate(client):
    assert client.get("/api/candidates/cand_does_not_exist/midi").status_code == 404
    assert client.get("/api/candidates/cand_does_not_exist/audio").status_code == 404


def test_midi_stem_endpoint_returns_attachment(client):
    cand = _start_one(client)
    parts = list((cand.get("midi_urls") or {}).keys())
    assert parts, "a generated candidate should expose at least one MIDI stem"
    part = parts[0]
    r = client.get(f"/api/candidates/{cand['candidate_id']}/midi/{part}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("audio/midi")
    cd = r.headers.get("content-disposition", "").lower()
    assert "attachment" in cd and part in cd  # filename carries the part
    assert r.content[:4] == b"MThd"


def test_midi_stem_404_for_unknown_part(client):
    cand = _start_one(client)
    assert client.get(f"/api/candidates/{cand['candidate_id']}/midi/notapart").status_code == 404


def test_midi_stem_404_for_unknown_candidate(client):
    assert client.get("/api/candidates/cand_nope/midi/bass").status_code == 404
