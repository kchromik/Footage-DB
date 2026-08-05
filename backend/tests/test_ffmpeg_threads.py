"""Begrenzung der ffmpeg-Threads.

Hintergrund: Ohne Begrenzung nimmt sich libx264 alle Kerne und legt pro
Thread eigene Frame-Puffer an. Bei mehreren Workern parallel vervielfacht
sich beides. Auf einer 8-Kern-NAS mit 7,4 GB RAM liefen dadurch vier
ffmpeg-Prozesse mit je acht Threads, einer davon mit 1,9 GB bei
6K-Quellmaterial. Das Gerät ging ins Swap-Thrashing, die Load stieg auf 101
und sämtliche anderen Dienste waren nicht mehr erreichbar.

Diese Tests halten fest, dass die Summe der Threads über alle Worker
ungefähr bei der Kernzahl bleibt und die Begrenzung in beiden Richtungen
im Kommando landet: für den Dekoder vor dem -i, für den Encoder danach.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.media import ffmpeg, preview


def test_threads_sinken_mit_steigender_worker_zahl():
    with patch.object(ffmpeg.os, "cpu_count", return_value=8):
        werte = {}
        for workers in (1, 2, 4, 8):
            with patch.object(
                type(ffmpeg.runtime), "worker_count", property(lambda _s, w=workers: w)
            ):
                werte[workers] = ffmpeg.thread_limit()
    assert werte == {1: 8, 2: 4, 4: 2, 8: 1}


def test_summe_der_threads_bleibt_bei_der_kernzahl():
    """Das ist die eigentliche Zusicherung: keine Überbuchung der CPU."""
    with patch.object(ffmpeg.os, "cpu_count", return_value=8):
        for workers in (1, 2, 3, 4, 8, 16):
            with patch.object(
                type(ffmpeg.runtime), "worker_count", property(lambda _s, w=workers: w)
            ):
                gesamt = ffmpeg.thread_limit() * workers
            assert gesamt <= 16, f"{workers} Worker buchen {gesamt} Threads"


def test_thread_limit_ist_nie_null():
    """Mehr Worker als Kerne darf nicht in -threads 0 münden."""
    with patch.object(ffmpeg.os, "cpu_count", return_value=2):
        with patch.object(
            type(ffmpeg.runtime), "worker_count", property(lambda _s: 32)
        ):
            assert ffmpeg.thread_limit() == 1


def test_thread_limit_ohne_erkennbare_kernzahl():
    with patch.object(ffmpeg.os, "cpu_count", return_value=None):
        assert ffmpeg.thread_limit() >= 1


def test_base_command_begrenzt_dekoder_und_filter():
    cmd = ffmpeg.base_command()
    assert "-threads" in cmd
    assert "-filter_threads" in cmd
    # Muss vor einem eventuellen -i stehen, sonst trifft es den Encoder
    # statt den Dekoder.
    assert "-i" not in cmd


def test_proxy_kommando_begrenzt_auch_den_encoder():
    args = preview._proxy_args_cpu(Path("/quelle.mov"), Path("/ziel.mp4"), True, None)
    assert args.count("-threads") == 2, "Dekoder- und Encoder-Seite erwartet"
    erste = args.index("-threads")
    eingabe = args.index("-i")
    zweite = args.index("-threads", eingabe)
    # Die erste Nennung steht vor dem -i und trifft damit den Dekoder.
    assert erste < eingabe
    # Die zweite steht danach und vor der Ausgabedatei, trifft also den
    # Encoder. Untereinander ist die Reihenfolge von -c:v und -threads egal,
    # ffmpeg wendet beide auf dieselbe Ausgabe an.
    assert eingabe < zweite < len(args) - 1
    assert args[zweite + 1].isdigit() and int(args[zweite + 1]) >= 1


def test_vorgabe_der_worker_zahl_beruecksichtigt_den_speicher():
    from app.config import default_worker_count

    # 8 Kerne, aber nur 4 GB RAM: der Speicher muss begrenzen, nicht die CPU.
    with patch("app.config.os.cpu_count", return_value=8), patch(
        "app.config.os.sysconf",
        side_effect=lambda name: 4096 if "PAGE_SIZE" in name else (4 * 1024**3) // 4096,
    ):
        assert default_worker_count() == 1

    # Grosse Maschine: nach oben trotzdem gedeckelt.
    with patch("app.config.os.cpu_count", return_value=64), patch(
        "app.config.os.sysconf",
        side_effect=lambda name: 4096 if "PAGE_SIZE" in name else (128 * 1024**3) // 4096,
    ):
        assert default_worker_count() == 4
