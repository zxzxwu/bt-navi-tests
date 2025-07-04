#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

#include "lc3.h"
#include <pybind11/pybind11.h>
namespace py = pybind11;

int SampleSize(int fmt) {
  switch (fmt) {
    case lc3_pcm_format::LC3_PCM_FORMAT_S16:
      return 2;
    case lc3_pcm_format::LC3_PCM_FORMAT_S24:
      return 3;
    case lc3_pcm_format::LC3_PCM_FORMAT_S24_3LE:
      return 3;
    case lc3_pcm_format::LC3_PCM_FORMAT_FLOAT:
      return 4;
    default:
      char msg[64];
      snprintf(msg, sizeof(msg), "Unknown fmt: %d", fmt);
      throw std::runtime_error(msg);
  }
}

class Encoder {
 public:
  Encoder(int duration_us, int sample_rate_hz, int pcm_sample_rate_hz)
      : duration_us_(duration_us),
        sample_rate_hz_(sample_rate_hz),
        pcm_sample_rate_hz_(pcm_sample_rate_hz),
        mem_(lc3_encoder_size(duration_us,
                              std::max(sample_rate_hz, pcm_sample_rate_hz))),
        encoder_(lc3_setup_encoder(duration_us, sample_rate_hz,
                                   pcm_sample_rate_hz, mem_.data())) {}
  py::bytes Encode(int fmt, const std::string &input, int output_size) {
    std::vector<char> output(output_size);
    auto ret = lc3_encode(encoder_, static_cast<lc3_pcm_format>(fmt),
                          input.data(), 1, output_size, output.data());
    if (ret == -1) {
      char msg[64];
      snprintf(msg, sizeof(msg), "Failed to encode: %d", ret);
      throw std::runtime_error(msg);
    }
    return py::bytes(output.data(), output.size());
  }
  int GetFrameSamples() {
    return lc3_frame_samples(duration_us_, sample_rate_hz_);
  }

 private:
  int duration_us_;
  int sample_rate_hz_;
  int pcm_sample_rate_hz_;
  std::vector<uint8_t> mem_;
  lc3_encoder_t encoder_;
};

class Decoder {
 public:
  Decoder(int duration_us, int sample_rate_hz, int pcm_sample_rate_hz)
      : duration_us_(duration_us),
        sample_rate_hz_(sample_rate_hz),
        pcm_sample_rate_hz_(pcm_sample_rate_hz),
        mem_(lc3_decoder_size(duration_us,
                              std::max(sample_rate_hz, pcm_sample_rate_hz))),
        decoder_(lc3_setup_decoder(duration_us, sample_rate_hz,
                                   pcm_sample_rate_hz, mem_.data())) {}
  py::bytes Decode(const std::string &input, int fmt) {
    std::vector<char> output(GetFrameSamples() * SampleSize(fmt));
    auto ret = lc3_decode(decoder_, input.data(), input.size(),
                          static_cast<lc3_pcm_format>(fmt), output.data(), 1);
    if (ret == -1) {
      char msg[64];
      snprintf(msg, sizeof(msg), "Failed to encode: %d", ret);
      throw std::runtime_error(msg);
    }
    return py::bytes(output.data(), output.size());
  }
  int GetFrameSamples() {
    return lc3_frame_samples(duration_us_, pcm_sample_rate_hz_);
  }

 private:
  int duration_us_;
  int sample_rate_hz_;
  int pcm_sample_rate_hz_;
  std::vector<uint8_t> mem_;
  lc3_decoder_t decoder_;
};

PYBIND11_MODULE(lc3_pybind, m) {
  py::class_<Encoder>(m, "Encoder")
      .def(py::init<int, int, int>())
      .def("encode", &Encoder::Encode)
      .def("get_frame_samples", &Encoder::GetFrameSamples);
  py::class_<Decoder>(m, "Decoder")
      .def(py::init<int, int, int>())
      .def("decode", &Decoder::Decode)
      .def("get_frame_samples", &Decoder::GetFrameSamples);
  py::enum_<lc3_pcm_format>(m, "PcmFormat")
      .value("S16", lc3_pcm_format::LC3_PCM_FORMAT_S16)
      .value("S24", lc3_pcm_format::LC3_PCM_FORMAT_S24)
      .value("S24_3LE", lc3_pcm_format::LC3_PCM_FORMAT_S24_3LE)
      .value("FLOAT", lc3_pcm_format::LC3_PCM_FORMAT_FLOAT);
}
