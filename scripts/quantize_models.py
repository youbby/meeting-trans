"""Store CTranslate2 Whisper weights as int8, the type the app loads them with.

The app always runs Whisper with compute_type="int8", so CTranslate2 quantizes the
float16 matrices on every load. Doing the same per-row quantization ahead of time
halves model.bin without changing what the runtime computes. Other variables
(biases, norms, conv kernels) are copied unchanged and converted at load as before.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import struct

import numpy as np

DTYPES = {0: np.float32, 1: np.int8, 2: np.int16, 3: np.int32, 4: np.float16}
INT8, FLOAT32 = 1, 0


def _read(stream, fmt):
    return struct.unpack(fmt, stream.read(struct.calcsize(fmt)))


def _read_string(stream):
    size, = _read(stream, "H")
    return stream.read(size)[:-1].decode("utf-8")


def _write_string(stream, value):
    data = value.encode("utf-8")
    stream.write(struct.pack("H", len(data) + 1) + data + b"\0")


def _load(path: Path):
    with path.open("rb") as stream:
        version, = _read(stream, "I")
        name = _read_string(stream)
        revision, = _read(stream, "I")
        count, = _read(stream, "I")
        variables = []
        for _ in range(count):
            key = _read_string(stream)
            rank, = _read(stream, "B")
            shape = _read(stream, f"{rank}I")
            dtype, = _read(stream, "B")
            size, = _read(stream, "I")
            variables.append((key, shape, dtype, stream.read(size)))
        aliases = [(_read_string(stream), _read_string(stream)) for _ in range(_read(stream, "I")[0])]
        if stream.read(1):
            raise ValueError("Unexpected data after model variables")
    return version, name, revision, variables, aliases


def _quantize(shape, data):
    # Same as CTranslate2's int8 conversion: per-row 127/amax scale, round half to even.
    value = np.frombuffer(data, np.float16).astype(np.float32).reshape(shape)
    amax = np.amax(np.absolute(value), axis=1)
    amax[amax == 0] = 127.0
    scale = (127.0 / amax).astype(np.float32)
    return np.rint(value * scale[:, None]).astype(np.int8), scale


def quantize_int8(path: Path) -> str | None:
    """Rewrite path in place; returns the source SHA-256, or None if already int8."""
    version, name, revision, variables, aliases = _load(path)
    names = {key for key, *_ in variables}
    output, quantized = [], set()
    for key, shape, dtype, data in variables:
        if key.endswith("weight") and len(shape) == 2 and dtype == 4 and f"{key}_scale" not in names:
            weight, scale = _quantize(shape, data)
            output += [(key, shape, INT8, weight.tobytes()), (f"{key}_scale", scale.shape, FLOAT32, scale.tobytes())]
            quantized.add(key)
        else:
            output.append((key, shape, dtype, data))
    if not quantized:
        return None
    # Tied weights (decoder projection = embeddings) also need their scale aliased.
    aliases = aliases + [(f"{alias}_scale", f"{target}_scale") for alias, target in aliases
        if target in quantized and f"{alias}_scale" not in dict(aliases)]
    with path.open("rb") as stream:
        source = hashlib.file_digest(stream, "sha256").hexdigest()
    part = path.with_suffix(path.suffix + ".part")
    with part.open("wb") as stream:
        stream.write(struct.pack("I", version))
        _write_string(stream, name)
        stream.write(struct.pack("II", revision, len(output)))
        for key, shape, dtype, data in output:
            _write_string(stream, key)
            stream.write(struct.pack(f"=B{len(shape)}IBI", len(shape), *shape, dtype, len(data)))
            stream.write(data)
        stream.write(struct.pack("I", len(aliases)))
        for alias, target in aliases:
            _write_string(stream, alias)
            _write_string(stream, target)
    os.replace(part, path)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("model", type=Path, nargs="+", help="CTranslate2 model.bin files")
    for path in parser.parse_args().model:
        before = path.stat().st_size
        result = quantize_int8(path)
        state = "already int8" if result is None else f"{before / 1024**2:.1f} -> {path.stat().st_size / 1024**2:.1f} MiB"
        print(f"{path}: {state}")


if __name__ == "__main__":
    main()
