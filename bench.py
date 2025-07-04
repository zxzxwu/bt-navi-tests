import timeit
import lc3
from navi.utils import lc3 as pybindlc3

navi_decoder = pybindlc3.Decoder(
    frame_duration_us=10000,
    sample_rate_hz=48000,
    pcm_sample_rate_hz=48000,
    num_channels=2,
)
dll_decoder = lc3.Decoder(
    frame_duration_us=10000,
    sample_rate_hz=48000,
    output_sample_rate_hz=48000,
    num_channels=2,
)

a = bytes([i for i in range(240)])
print("decode")
print(
    "pybind: %fs"
    % timeit.timeit(
        lambda: navi_decoder.decode(a, pybindlc3.PcmFormat.SIGNED_16), number=10000
    )
)
print(
    "dll: %fs"
    % timeit.timeit(lambda: dll_decoder.decode(a, bit_depth=16), number=10000)
)


navi_encoder = pybindlc3.Encoder(
    frame_duration_us=10000,
    sample_rate_hz=48000,
    input_sample_rate_hz=48000,
    num_channels=2,
)
dll_encoder = lc3.Encoder(
    frame_duration_us=10000,
    sample_rate_hz=48000,
    input_sample_rate_hz=48000,
    num_channels=2,
)
b = bytes(48000 // 1000 * 10 * 2 * 2)
print("encode")
print(
    "pybind: %fs"
    % timeit.timeit(
        lambda: navi_encoder.encode(b, 240, pybindlc3.PcmFormat.SIGNED_16), number=10000
    )
)
print(
    "dll: %fs"
    % timeit.timeit(lambda: dll_encoder.encode(b, 240, bit_depth=16), number=10000)
)
