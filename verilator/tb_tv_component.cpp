// Independent integer-matrix oracle; exhaustive RGB888 and blanking/reset tags.
#include "Vtv_component.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
struct Sample { uint32_t code, tag; };
uint32_t convert(uint32_t rgb, bool de) {
    int r=de ? (rgb>>16)&255 : 0, g=de ? (rgb>>8)&255 : 0, b=de ? rgb&255 : 0;
    auto q=[](int v) { return v<0 ? 0 : v>=65536 ? 255 : v/256; };
    return (q(32768+128*r-106*g-21*b)<<16) |
           (q(77*r+150*g+29*b)<<8) | q(32768-42*r-85*g+128*b);
}
int main(int argc,char** argv) try {
    Verilated::commandArgs(argc,argv);
    Vtv_component dut;
    constexpr uint32_t idle=7u<<26;
    std::array<Sample,3> queue{};
    uint64_t checks=0;
    auto step=[&](uint32_t rgb,bool de,uint32_t tag,bool reset) {
        dut.clk=0; dut.reset=reset; dut.rgb=rgb; dut.picture_de=de; dut.tag_in=tag; dut.eval();
        if(reset) queue.fill({0x800080,idle});
        else { queue[2]=queue[1]; queue[1]=queue[0]; queue[0]={convert(rgb,de),tag}; }
        dut.clk=1; dut.eval();
        if(dut.component!=queue[2].code || dut.tag_out!=queue[2].tag)
            throw std::runtime_error("component/tag mismatch at sample "+std::to_string(checks));
        ++checks;
    };
    step(0,false,0,true);
    for(uint32_t rgb=0;rgb<0x1000000;++rgb)
        step(rgb,true,(rgb*1777u) & 0x1fffffff,false);
    for(unsigned n=0;n<256;++n) {
        uint32_t gray=n*0x010101;
        if(convert(gray,true)!=(0x800080u|(n<<8))) throw std::runtime_error("gray neutrality");
        step(gray,true,n,false);
        step(gray,false,n|0x10000000,false);
    }
    uint32_t rng=0x52527;
    for(unsigned n=0;n<10000;++n) {
        rng^=rng<<13; rng^=rng>>17; rng^=rng<<5;
        step(rng&0xffffff,rng&1,rng&0x1fffffff,n%127==0);
    }
    for(unsigned n=0;n<3;++n) step(0,false,0,false);
    std::cout<<"PASS: all 16,777,216 RGB888 inputs, 256 neutral grays, blanking, "
             <<"random tags and 79 reset interruptions; "<<checks<<" pipeline checks\n";
} catch(const std::exception& e) { std::cerr<<"FAIL: "<<e.what()<<"\n"; return 1; }
