#include "Vtv_v8_pipeline.h"
#include "verilated.h"
#include <array>
#include <vector>
#include <algorithm>
#include <stdexcept>
#include <iostream>
#include <cstdint>

static uint32_t color(int x,int y) {
    unsigned p=(x^y)&255;
    return p<<16 | (p^0x5a)<<8 | (p^255);
}
static void run(bool twelve, bool pattern=true) {
    Vtv_v8_pipeline d;
    std::vector<std::array<uint32_t,4>> ram(262144);
    uint64_t t=0,ns=79,nm=43,nt=111,source_ticks=0,source_pixels=0,tv_pixels=0;
    unsigned remaining=0,index=0,delay=0,base=0,wremaining=0,windex=0,wbase=0;
    int pairs=0;bool acquired=false,seen_picture=false;
    int w=twelve?512:640,h=twelve?384:480,totalx=twelve?640:800,totaly=twelve?407:525;
    d.monitor_id=twelve?2:6;d.source_ce=1;d.test_pattern=pattern;d.reset_tv=1;d.reset_source=1;
    d.eval();
    auto fail=[&](const char* why){throw std::runtime_error(std::string(why)+" ps="+std::to_string(t));};
    while(pairs<6) {
        t=std::min({ns,nm,nt});
        bool s=t==ns,m=t==nm,v=t==nt;
        bool sr=s&&!d.clk_source,mr=m&&!d.clk_mem,vr=v&&!d.clk_tv;
        d.reset_source=t<2000000;d.reset_tv=t<1000000;
        if(mr) {
            d.waitrequest=((t/10000)%19)==0;d.readdatavalid=0;
            if(remaining) {
                if(delay)--delay;
                else {d.readdatavalid=1;for(int k=0;k<4;k++)d.readdata[k]=ram.at(base+index)[k];}
            }
        }
        d.eval();uint32_t tag=d.tag_raw;
        if(mr) {
            if(d.read&&!d.waitrequest) {
                if(remaining||wremaining)fail("native overlapping memory commands");
                base=d.address-0x2180000;remaining=d.burstcount;index=0;delay=27;
            }
            if(d.write&&!d.waitrequest) {
                if(!wremaining){wbase=d.address-0x2180000;wremaining=d.burstcount;windex=0;}
                for(int k=0;k<4;k++) {
                    if(d.writedata[k]&0xff000000)fail("native capture padding mismatch");
                    ram.at(wbase+windex)[k]=d.writedata[k];
                }
                --wremaining;++windex;
            }
            if(d.readdatavalid){--remaining;++index;}
        }
        if(s){d.clk_source=!d.clk_source;ns+=twelve?31921:19861;}
        if(m){d.clk_mem=!d.clk_mem;nm+=5000;}
        if(v){d.clk_tv=!d.clk_tv;nt+=18518;}
        d.eval();
        if(sr&&!d.reset_source) {
            if(d.native_frame) {
                if(acquired && source_ticks!=uint64_t(totalx*totaly))fail("native frame period changed");
                acquired=true;source_ticks=0;
            }
            if(acquired) {
                auto phase=source_ticks%(totalx*totaly);unsigned x=phase%totalx,y=phase/totalx;
                bool active=x<unsigned(w)&&y<unsigned(h);
                if(bool(d.native_de)!=active || bool(d.native_line)!=(x==0&&y<unsigned(h)) ||
                   bool(d.native_frame)!=(phase==0) || !d.native_ce || d.native_width!=w || d.native_height!=h)
                    fail("native marker, CE, metadata or DE latency mismatch");
                if(active) {if(d.native_rgb!=(pattern?color(x,y):color(0,0)))fail("native CLUT latency mismatch");++source_pixels;}
                ++source_ticks;
            }
        }
        if(vr&&!d.reset_tv) {
            if(tag&(1u<<22)){++pairs;if(d.published)seen_picture=true;}
            if(tag&(1u<<25)) {
                int x=(tag>>9)&1023,y=tag&511;
                bool inside=x>=(640-w)/2&&x<(640+w)/2&&y>=(480-h)/2&&y<(480+h)/2;
                if(seen_picture && d.rgb_raw!=(inside?(pattern?color(x-(640-w)/2,y-(480-h)/2):color(0,0)):0u))fail("native canvas pixel or border mismatch");
                if(seen_picture && (tag&(1u<<24)))++tv_pixels;
            }
        }
    }
    if(d.overflows||d.underruns||d.published<4||tv_pixels<1000000)fail("native coverage or buffer faults");
    std::cout<<"PASS V8 "<<w<<"x"<<h<<(pattern?" XOR":" VRAM")<<" source_pixels="<<source_pixels<<" canvas_pixels="<<tv_pixels
             <<" published="<<d.published<<" overflow="<<d.overflows<<" underrun="<<d.underruns<<std::endl;
}
// Verify the historic /2 CE and portrait mode on the real V8 as well.
// No DDR/TV clock is advanced here; this check is solely the native tap.
static void tap(unsigned monitor, bool gaps) {
    Vtv_v8_pipeline d;
    const unsigned w=monitor==2?512:640, h=monitor==1?870:monitor==2?384:480;
    const unsigned tx=monitor==1?832:monitor==2?640:800;
    const unsigned ty=monitor==1?918:monitor==2?407:525;
    uint64_t pixels=0,phase=0;
    unsigned frames=0;
    bool acquired=false;
    d.monitor_id=monitor;d.reset_tv=1;d.test_pattern=1;
    // Reset during a partial frame, and verify reacquisition afterwards.
    const uint64_t reset_at=uint64_t(tx)*17*(gaps?2:1)+100;
    for(uint64_t edge=0;frames<4 && edge<20000000; ++edge) {
        d.reset_source=edge<32 || (edge>=reset_at && edge<reset_at+16);
        if(d.reset_source)acquired=false;
        d.source_ce=!gaps || (edge&1);
        d.clk_source=0;d.eval();d.clk_source=1;d.eval();
        if(d.reset_source || !d.native_ce)continue;
        if(d.native_frame) {
            if(acquired && phase!=uint64_t(tx)*ty)throw std::runtime_error("V8 CE/reset frame period");
            acquired=true;phase=0;++frames;
        }
        if(!acquired)continue;
        unsigned x=phase%tx,y=phase/tx;
        bool active=x<w && y<h;
        if(bool(d.native_de)!=active || bool(d.native_line)!=(x==0&&y<h) ||
           bool(d.native_frame)!=(phase==0) ||
           d.native_width!=(monitor==1?0:w) || d.native_height!=(monitor==1?0:h))
            throw std::runtime_error("V8 CE/reset/unsupported geometry marker alignment");
        if(active){if(d.native_rgb!=color(x,y))throw std::runtime_error("V8 CE palette alignment");++pixels;}
        ++phase;
    }
    if(frames<4)throw std::runtime_error("V8 native tap coverage");
    std::cout<<"PASS V8 tap monitor="<<monitor<<" CE="<<(gaps?"/2":"1")
             <<" reset reacquisition pixels="<<pixels<<" geometry="<<d.native_width<<"x"<<d.native_height<<std::endl;
}
int main(int argc,char**argv) {
    Verilated::commandArgs(argc,argv);
    try{run(true);run(false);run(true,false);run(false,false);tap(2,true);tap(6,true);tap(1,false);}
    catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<std::endl;return 1;}
}
