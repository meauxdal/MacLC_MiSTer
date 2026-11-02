#include "Vtv525_pipeline.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

#ifndef TV_FILTER_ENABLE
#define TV_FILTER_ENABLE 0
#endif
#ifndef TV_BASE_WORD
#define TV_BASE_WORD 0x2180000
#endif
#ifndef TV_SOURCE_WIDTH
#define TV_SOURCE_WIDTH 0
#endif
#ifndef TV_SOURCE_HEIGHT
#define TV_SOURCE_HEIGHT 0
#endif

static uint32_t color(int x, int y) {
    return uint32_t((x*13+y*3+1)&255)<<16 |
           uint32_t((y*7+x*5)&255)<<8 | uint32_t((x^y)&255);
}

static uint32_t filtered(int x, int y, int height, int mode) {
    if (!TV_FILTER_ENABLE || mode==0) return color(x,y);
    uint32_t a=color(x,std::max(0,y-1)), c=color(x,y);
    uint32_t b=color(x,std::min(height-1,y+1)), result=0;
    int weight=mode==1 ? 6 : 2, divisor=weight+2;
    for (int shift : {0,8,16}) {
        unsigned sum=((a>>shift)&255)+weight*((c>>shift)&255)+((b>>shift)&255);
        result|=((sum+divisor/2)/divisor)<<shift;
    }
    return result;
}

struct Sim {
    Vtv525_pipeline d;
    std::vector<uint64_t> ram=std::vector<uint64_t>(524288);
    uint64_t time=0, next_tv=111, next_mem=43, next_source=79;
    uint64_t samples=0;
    unsigned cycle=0, sx=0, sy=0, source_edges=0, checked=0;
    unsigned read_left=0, read_base=0, read_index=0, read_delay=0;
    unsigned write_left=0, write_base=0, write_index=0, write_count=0;
    unsigned width, height, total_x, total_y, source_half, mode;
    bool source_advance=false, source_reset_test=false, switch_geometry=false;

    Sim(unsigned w, unsigned h, unsigned strength): width(w), height(h), mode(strength) {
        total_x=w==640 ? 800 : 640;
        total_y=h==480 ? 525 : h==384 ? 407 : std::max(h+28,370u);
        source_half=h==480 ? 9930 : 16666;
        d.source_width=w; d.source_height=h; d.filter_mode=mode;
        d.clk_tv=0; d.clk_mem=0; d.clk_source=0;
        d.reset_tv=1; d.source_reset=1; d.inhibit=0;
        d.waitrequest=0; d.readdatavalid=0; d.readdata=0;
        d.source_ce=0; d.source_de=0; d.source_line=0; d.source_frame=0; d.source_rgb=0;
    }
    void require(bool ok, const char *message) {
        if (!ok) throw std::runtime_error(std::string(message)+" at sample "+std::to_string(samples));
    }
    unsigned offset(unsigned addr) {
        require(addr>=TV_BASE_WORD*2u && addr<TV_BASE_WORD*2u+ram.size(),"DDR reservation");
        return addr-TV_BASE_WORD*2u;
    }
    void memory_before() {
        d.waitrequest=cycle%7==0 || cycle%11==3;
        d.readdatavalid=read_left && !read_delay && cycle%5!=0;
        if (read_delay) --read_delay;
        if (d.readdatavalid) d.readdata=ram.at(offset(read_base+read_index));
    }
    void memory_accept() {
        if (d.readdatavalid) { --read_left; ++read_index; }
        if ((d.read || d.write) && !d.waitrequest) {
            require(d.burstcount>0 && d.burstcount<=128,"DDR burst length");
            require(!(d.read && d.write),"simultaneous DDR read/write");
            if (d.read) {
                require(!read_left && !write_left,"overlapping DDR commands");
                read_left=d.burstcount; read_base=d.address; read_index=0; read_delay=3;
            } else {
                require(!read_left,"write during DDR read response");
                if (!write_left) {
                    write_left=d.burstcount; write_count=d.burstcount;
                    write_base=d.address; write_index=0;
                }
                require(d.address==write_base && d.burstcount==write_count,"unstable DDR write command");
                require(d.byteenable==255,"RGBx byte enables");
                ram.at(offset(write_base+write_index++))=d.writedata;
                --write_left;
            }
        }
        ++cycle;
    }
    void source_before() {
        // Half-rate CE exercises filter and capture pipelines between pixels.
        source_advance=total_x==width || (source_edges++&1)==0;
        source_reset_test=samples>=2100000 && samples<2100100;
        d.source_reset=time<1000000 || source_reset_test;
        d.source_width=width; d.source_height=height;
        d.source_ce=source_advance;
        d.source_de=sx<width && sy<height;
        d.source_line=d.source_de && sx==0;
        d.source_frame=d.source_line && sy==0;
        d.source_rgb=color(sx,sy);
    }
    void source_after() {
        if (!source_advance) return;
        if (++sx==total_x) { sx=0; if (++sy==total_y) {
            sy=0;
            if (switch_geometry && time>20000000000ULL) { width=319; height=239; }
        }}
    }
    void tv_after() {
        if (d.reset_tv) return;
        unsigned p=samples%900900, h=p%1716, line=p/1716;
        unsigned half=(p%450450)/858, s=p%858;
        bool odd=p<450450, broad=half>=6 && half<12;
        bool eq=half<6 || (half>=12 && half<18);
        bool de=(odd ? line>=22 && line<262 : line>=284 && line<524) && h>=253 && h<1675;
        bool cs=!(eq ? s<62 : broad ? s<731 : h<127);
        require(d.hs==(h>=127) && d.vs==!broad && d.csync_n==cs,"raster sync");
        require(d.field_id==odd && d.de==de,"field parity/aperture");
        if (!de) require(d.rgb==0,"RGB outside aperture");
        if (samples>=1801800 && de) {
            int x=(h-253)*640/1422;
            int y=(line-(odd ? 22 : 284))*2+(odd ? 1 : 0);
            int ox=(640-width)/2, oy=(480-height)/2;
            bool inside=x>=ox && x<ox+int(width) && y>=oy && y<oy+int(height);
            uint32_t expected=inside ? filtered(x-ox,y-oy,height,mode) : 0;
            if (d.rgb!=expected) {
                std::cerr<<"RGB "<<width<<'x'<<height<<" mode="<<mode<<" x="<<x<<" y="<<y
                         <<" actual="<<d.rgb<<" expected="<<expected<<" published="<<d.published
                         <<" dropped="<<d.dropped<<" overflow="<<d.overflows<<" underrun="<<d.underruns<<'\n';
                require(false,"woven RGB/filter/centering");
            }
            ++checked;
        }
        ++samples;
    }
    void run() {
        d.eval();
        while (samples<2702700) {
            time=std::min({next_tv,next_mem,next_source});
            bool tv=time==next_tv, mem=time==next_mem, source=time==next_source;
            bool tv_r=tv && !d.clk_tv, mem_r=mem && !d.clk_mem, source_r=source && !d.clk_source;
            if (mem_r) memory_before();
            if (source_r) source_before();
            if (tv_r) d.reset_tv=time<1000000;
            d.eval();
            if (mem_r) memory_accept();
            if (tv) { d.clk_tv=!d.clk_tv; next_tv+=18518; }
            if (mem) { d.clk_mem=!d.clk_mem; next_mem+=7692; }
            if (source) { d.clk_source=!d.clk_source; next_source+=source_half; }
            d.eval();
            if (tv_r) tv_after();
            if (source_r) source_after();
        }
        require(checked==682560 && d.published>0,"full field-pair coverage");
        require(d.overflows==0 && d.underruns==0,"healthy DDR service faults");
        std::cout<<"PASS "<<width<<'x'<<height<<" filter="<<mode<<" samples="<<checked<<'\n';
    }
};

int main(int argc, char **argv) {
    Verilated::commandArgs(argc,argv);
    try {
        for (unsigned mode=0; mode<(TV_FILTER_ENABLE ? 3u : 1u); ++mode) {
            if (TV_SOURCE_WIDTH && TV_SOURCE_HEIGHT) {
                Sim(TV_SOURCE_WIDTH,TV_SOURCE_HEIGHT,mode).run();
                continue;
            }
            Sim(512,342,mode).run();
            Sim(512,384,mode).run();
            Sim(640,480,mode).run();
            Sim(639,479,mode).run();
            Sim(5,7,mode).run();
            Sim(1,1,mode).run();
            Sim narrow(1,3,mode); narrow.total_x=1; narrow.source_half=39722; narrow.run();
            Sim changing(640,480,mode); changing.switch_geometry=true; changing.run();
        }
    } catch (const std::exception &e) {
        std::cerr<<"FAIL "<<e.what()<<'\n';
        return 1;
    }
}
