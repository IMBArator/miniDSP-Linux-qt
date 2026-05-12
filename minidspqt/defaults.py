from functools import lru_cache

from minidsp.defaults import load_factory_defaults


@lru_cache(maxsize=1)
def _factory() -> dict:
    return load_factory_defaults()["params"]


def default_gate_state() -> tuple:
    g = _factory()["gates"][0]
    return g["attack"], g["release"], g["hold"], g["threshold"]


def default_crossover_state() -> tuple:
    x = _factory()["crossovers"][0]
    return x["hipass_freq"], x["hipass_slope"], x["lopass_freq"], x["lopass_slope"]


def default_compressor_state() -> tuple:
    c = _factory()["compressors"][0]
    return c["ratio"], c["knee"], c["attack"], c["release"], c["threshold"]


def default_peq_bands() -> list[tuple]:
    bands = _factory()["peqs"][0]["bands"]
    return [(b["gain"], b["freq"], b["q"], b["type"], b["bypass"]) for b in bands]


def default_peq_channel_bypass() -> bool:
    return _factory()["peqs"][0]["channel_bypass"]
