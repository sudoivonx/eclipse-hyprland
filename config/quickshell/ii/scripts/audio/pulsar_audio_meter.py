#!/usr/bin/env python3
"""Transient PipeWire output-monitor meter for Pulsar; never writes audio."""
import argparse
import array
import json
import math
import signal
import subprocess
import sys

SAMPLE_RATE = 22050
FRAME_COUNT = 1024
stopping = False
recorder = None


def request_stop(_signum, _frame):
    global stopping
    stopping = True
    if recorder is not None and recorder.poll() is None:
        try:
            recorder.terminate()
        except ProcessLookupError:
            pass


def read_frame(stream, byte_count):
    chunks = []
    remaining = byte_count
    while remaining and not stopping:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def make_analyzer(bar_count):
    window = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (FRAME_COUNT - 1))
              for i in range(FRAME_COUNT)]
    window_sum = sum(window)
    min_hz, max_hz = 55.0, SAMPLE_RATE / 2.0 - SAMPLE_RATE / FRAME_COUNT
    freqs = [min_hz * (max_hz / min_hz) ** (i / max(1, bar_count - 1))
             for i in range(bar_count)]
    coeffs = []
    for freq in freqs:
        bin_index = max(1, min(FRAME_COUNT // 2 - 1,
                               round(freq * FRAME_COUNT / SAMPLE_RATE)))
        coeffs.append(2.0 * math.cos(2.0 * math.pi * bin_index / FRAME_COUNT))

    def analyze(samples):
        values = []
        for coeff in coeffs:
            q1 = q2 = 0.0
            for sample, weight in zip(samples, window):
                q0 = coeff * q1 - q2 + (sample / 32768.0) * weight
                q2, q1 = q1, q0
            power = max(0.0, q1 * q1 + q2 * q2 - coeff * q1 * q2)
            magnitude = 2.0 * math.sqrt(power) / window_sum
            db = 20.0 * math.log10(max(magnitude, 1e-7))
            # Noise gate below -54 dBFS, then a gentle display range.
            level = 0.0 if db < -54.0 else min(1.0, (db + 54.0) / 42.0)
            values.append(round(level, 4))
        return values

    return analyze


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True, help='PipeWire output sink node id')
    parser.add_argument('--bars', type=int, default=32)
    args = parser.parse_args()
    bars = max(8, min(args.bars, 64))
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    global recorder
    command = [
        'pw-record', '--target', args.target, '--raw', '--format', 's16',
        '--rate', str(SAMPLE_RATE), '--channels', '1',
        '--properties', 'application.name=Pulsar Audio Visualizer', '-'
    ]
    try:
        recorder = subprocess.Popen(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, bufsize=0)
    except OSError as error:
        print(json.dumps({'error': 'Could not start PipeWire capture: ' + str(error)}),
              flush=True)
        return 1

    analyze = make_analyzer(bars)
    byte_count = FRAME_COUNT * 2
    try:
        while not stopping:
            raw = read_frame(recorder.stdout, byte_count)
            if stopping or len(raw) < byte_count:
                break
            samples = array.array('h')
            samples.frombytes(raw)
            if sys.byteorder != 'little':
                samples.byteswap()
            print(json.dumps(analyze(samples), separators=(',', ':')), flush=True)
        if not stopping:
            return_code = recorder.wait()
            detail = recorder.stderr.read().decode('utf-8', 'replace').strip()
            if return_code != 0:
                message = detail or 'PipeWire monitor ended unexpectedly.'
                print(json.dumps({'error': message}), flush=True)
                return return_code or 1
    finally:
        if recorder.poll() is None:
            recorder.terminate()
            try:
                recorder.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                recorder.kill()
                recorder.wait()
        if recorder.stdout:
            recorder.stdout.close()
        if recorder.stderr:
            recorder.stderr.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
