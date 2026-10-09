// Actual ASCAL progressive video and its real Avalon master, compared with
// direct DDR service and with continuous 160-beat TV reads through our arbiter.
#include "Vhdmi_fixture.h"
#include "verilated.h"
#include <array>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <unordered_map>
#include <vector>

using Word = std::array<uint32_t, 4>;
struct Record {
    unsigned address;
    Word data;
    bool operator==(const Record& other) const {
        return address == other.address && data == other.data;
    }
};
struct Result {
    std::vector<Record> writes;
    std::vector<uint32_t> pixels;
    unsigned active = 0, nonblack = 0, tv_reads = 0;
};
struct Geometry {
    unsigned width, height, htotal, vtotal, hs, he, vs, ve;
};

Result run(const Geometry& g, bool bypass) {
    Vhdmi_fixture d;
    d.bypass = bypass;
    d.tv_read = 1;
    d.reset_na = 0;
    d.i_ce = d.o_ce = d.iauto = d.run = 1;
    d.mode = 8; // Triple-buffered, nearest, progressive; native f1/bob are zero.
    d.format = 1; // Framework default: packed 24-bit RGB.
    d.htotal = g.htotal; d.hsstart = g.hs; d.hsend = g.he;
    d.hdisp = g.width; d.hmin = 0; d.hmax = g.width - 1;
    d.vtotal = g.vtotal; d.vsstart = g.vs; d.vsend = g.ve;
    d.vdisp = g.height; d.vmin = 0; d.vmax = g.height - 1;
    std::unordered_map<unsigned, Word> memory;
    std::deque<std::pair<unsigned, unsigned>> reads;
    Result result;
    unsigned remaining = 0, write_address = 0, write_index = 0, x = 0, y = 0;
    bool old_input_clock = false;
    const unsigned frame_ticks = g.htotal * g.vtotal * 8;
    // 100 MHz DDR, 25 MHz source/output: deliberately stress both geometries
    // at VGA rate. These are functional clocks, not PLL/timing qualification.
    for (unsigned t = 0; t < frame_ticks * 6; ++t) {
        bool memory_clock = t % 2, input_clock = (t / 4) % 2;
        d.avl_clk = 0; d.i_clk = old_input_clock; d.o_clk = input_clock;
        d.poly_clk = d.pal1_clk = d.pal2_clk = 0;
        d.reset_na = t > 128;
        d.i_hs = x >= g.hs && x < g.he;
        d.i_vs = y >= g.vs && y < g.ve;
        d.i_de = x < g.width && y < g.height;
        d.i_r = (x ^ y) & 255;
        d.i_g = (x * 3 + y * 7) & 255;
        d.i_b = (x * 11 + y * 13) & 255;
        d.waitrequest = t % 34 == 1;
        d.readdatavalid = memory_clock && !reads.empty();
        Word response{};
        if (!reads.empty()) response = memory[reads.front().first];
        for (unsigned k = 0; k < 4; ++k) d.readdata[k] = response[k];
        d.eval();
        if (memory_clock) {
            if (d.readdatavalid) {
                auto& r = reads.front();
                ++r.first;
                if (!--r.second) reads.pop_front();
            }
            if (d.read && !d.waitrequest) {
                if (!d.burstcount) throw std::runtime_error("zero read burst");
                reads.emplace_back(d.address, d.burstcount);
                if (d.address >= 0x2180000) ++result.tv_reads;
            }
            if (d.write && !d.waitrequest) {
                if (!remaining) {
                    write_address = d.address;
                    write_index = 0;
                    remaining = d.burstcount;
                    if (!remaining) throw std::runtime_error("zero write burst");
                }
                Word word;
                for (unsigned k = 0; k < 4; ++k) word[k] = d.writedata[k];
                if (d.byteenable != 65535) throw std::runtime_error("masked picture write");
                memory[write_address + write_index] = word;
                // Buffer ownership may legally differ by slot; image-relative
                // addresses and every captured byte must still match.
                result.writes.push_back({(write_address + write_index) & 0x7ffff, word});
                ++write_index;
                --remaining;
            }
        }
        d.avl_clk = memory_clock; d.i_clk = input_clock;
        d.eval();
        if (input_clock && !old_input_clock) {
            if (++x == g.htotal) { x = 0; if (++y == g.vtotal) y = 0; }
            // Let image-size detection and triple buffering settle, then
            // compare the whole progressive RGB/DE/HS/VS stream for 3 frames.
            if (t > frame_ticks * 3) {
                uint32_t pixel = (uint32_t(d.o_r) << 24) | (uint32_t(d.o_g) << 16)
                    | (uint32_t(d.o_b) << 8) | (d.o_de << 2) | (d.o_hs << 1) | d.o_vs;
                result.pixels.push_back(pixel);
                if (d.o_de) { ++result.active; if (pixel >> 8) ++result.nonblack; }
            }
        }
        old_input_clock = input_clock;
    }
    if (result.writes.size() < 100000 || result.active != g.width * g.height * 3
        || result.nonblack < result.active / 2 || (!bypass && result.tv_reads < 100))
        throw std::runtime_error("insufficient real picture/TV traffic coverage");
    return result;
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    try {
        for (auto g : {Geometry{640,480,800,525,656,752,490,492},
                       Geometry{512,384,640,407,528,592,385,388}}) {
            auto direct = run(g, true), shared = run(g, false);
            if (direct.writes != shared.writes) throw std::runtime_error("ASCAL capture byte mismatch");
            if (direct.pixels != shared.pixels) throw std::runtime_error("progressive HDMI pixel/sync mismatch");
            std::cout << "PASS actual ASCAL " << g.width << "x" << g.height
                << " write_beats=" << shared.writes.size() << " output_samples=" << shared.pixels.size()
                << " active_pixels=" << shared.active << " tv_read_bursts=" << shared.tv_reads << '\n';
        }
    } catch (const std::exception& e) { std::cerr << "FAIL " << e.what() << '\n'; return 1; }
}
