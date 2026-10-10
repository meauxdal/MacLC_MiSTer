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
static unsigned index_at(int x,int y,int mode) {
    unsigned value=unsigned(x*13+y*7+(x/11)*19+(y/9)*23);
    switch(mode) {
        case 0:return ((value&1)<<7)|127;
        case 1:return ((value&3)<<6)|63;
        case 2:return ((value&15)<<4)|15;
        default:return value&255;
    }
}
static uint32_t actual_color(int x,int y,int mode) {
    if(mode==4) {
        unsigned p=unsigned(x*13+y*7+(x/11)*19+(y/9)*23)&32767;
        return ((p>>10)&31)<<19 | ((p>>5)&31)<<11 | (p&31)<<3;
    }
    unsigned p=index_at(x,y,mode);
    return p<<16 | (p^0x5a)<<8 | (p^255);
}
static void prepare(Vtv_v8_pipeline &d,int w,int h,int mode) {
    auto tick=[&](){d.clk_mem=0;d.eval();d.clk_mem=1;d.eval();};
    d.reset_palette=1;tick();tick();d.reset_palette=0;
    for(int i=0;i<260;i++)tick();
    auto access=[&](bool address,unsigned value) {
        d.cpu_palette_addr=0;d.cpu_palette_data=value;
        d.cpu_palette_req=1;d.cpu_palette_we=1;d.cpu_palette_as_n=0;
        d.cpu_palette_uds_n=!address;d.cpu_palette_lds_n=address;
        // Several latch opportunities per access must still advance once.
        for(int i=0;i<4;i++)tick();
        d.cpu_palette_req=0;d.cpu_palette_we=0;d.cpu_palette_as_n=1;
        for(int i=0;i<3;i++)tick();
    };
    access(true,0);
    for(unsigned p=0;p<256;p++){access(false,p);access(false,p^0x5a);access(false,p^255);}
    unsigned bpp=1u<<mode,ppw=16/bpp,wpl=w/ppw;
    d.cpu_vram_we=1;d.cpu_vram_be=3;
    for(int y=0;y<h;y++)for(unsigned word=0;word<wpl;word++) {
        unsigned packed=0;
        for(unsigned px=0;px<ppw;px++) {
            unsigned index=index_at(word*ppw+px,y,mode);
            unsigned value=mode==4?unsigned((word*ppw+px)*13+y*7+((word*ppw+px)/11)*19+(y/9)*23)&32767:
                           mode==3?index:index>>(8-bpp);
            packed=(packed<<bpp)|value;
        }
        d.cpu_vram_addr=y*wpl+word;d.cpu_vram_data=packed;tick();
    }
    d.cpu_vram_we=0;d.clk_mem=0;d.eval();
}
static void run(bool twelve, bool pattern=true,int actual_mode=-1,bool drawing=false) {
    Vtv_v8_pipeline d;
    std::vector<std::array<uint32_t,4>> ram(262144);
    uint64_t t=0,ns=79,nm=43,nt=111,source_ticks=0,source_pixels=0,tv_pixels=0;
    unsigned remaining=0,index=0,delay=0,base=0,wremaining=0,windex=0,wbase=0;
    int pairs=0;bool acquired=false,seen_picture=false;
    unsigned native_frames=0;
    unsigned draw_words=0;
    std::vector<uint32_t> native_snapshot;
    std::vector<std::vector<uint32_t>> completed;
    std::vector<unsigned> candidates;
    int w=twelve?512:640,h=twelve?384:480,totalx=twelve?640:800,totaly=twelve?407:525;
    d.monitor_id=twelve?2:6;d.source_ce=1;d.test_pattern=pattern;d.reset_tv=1;d.reset_source=1;
    d.actual_memory=actual_mode>=0;d.video_mode=actual_mode>=0?actual_mode:3;
    if(d.actual_memory)prepare(d,w,h,actual_mode);
    auto expected=[&](int x,int y){return actual_mode>=0?actual_color(x,y,actual_mode):pattern?color(x,y):color(0,0);};
    d.eval();
    auto fail=[&](const char* why){throw std::runtime_error(std::string(why)+" ps="+std::to_string(t));};
    while(pairs<(actual_mode>=0?8:6)) {
        t=std::min({ns,nm,nt});
        bool s=t==ns,m=t==nm,v=t==nt;
        bool sr=s&&!d.clk_source,mr=m&&!d.clk_mem,vr=v&&!d.clk_tv;
        d.reset_source=t<2000000;d.reset_tv=t<1000000;
        if(mr) {
            // A sustained CPU drawing burst crosses native frames and TV
            // fields. The TV oracle is the exact complete RAW source image,
            // allowing native write/scanout tearing but never TV pair tearing.
            if(drawing) {
                d.cpu_vram_we=t>60000000000ULL && t<80000000000ULL;
                unsigned wpl=w*(1u<<actual_mode)/16;
                d.cpu_vram_addr=draw_words%(wpl*h);
                d.cpu_vram_data=(draw_words*31337u)^(draw_words>>7)^0xa531u;
                if(d.cpu_vram_we)++draw_words;
            }
            d.waitrequest=((t/10000)%19)==0;d.readdatavalid=0;
            if(remaining) {
                if(delay)--delay;
                else {
                    d.readdatavalid=1;
                    unsigned word=base+index,lane=(word&1)*2;
                    const auto &data=ram.at(word>>1);
                    d.readdata=uint64_t(data[lane])|(uint64_t(data[lane+1])<<32);
                }
            }
        }
        d.eval();uint32_t tag=d.tag_raw;
        if(drawing && sr && !d.reset_source && d.native_ce && d.native_de) {
            if(d.native_frame)native_snapshot.clear();
            native_snapshot.push_back(d.native_rgb);
            if(native_snapshot.size()==unsigned(w*h))completed.push_back(native_snapshot);
        }
        if(mr) {
            if(d.read&&!d.waitrequest) {
                if(remaining||wremaining)fail("native overlapping memory commands");
                base=d.address-0x4300000;remaining=d.burstcount;index=0;delay=27;
            }
            if(d.write&&!d.waitrequest) {
                if(!wremaining){wbase=d.address-0x4300000;wremaining=d.burstcount;windex=0;}
                for(int k=0;k<2;k++) {
                    uint32_t data=uint32_t(d.writedata>>(k*32));
                    if(data&0xff000000)fail("native capture padding mismatch");
                    unsigned word=wbase+windex;
                    ram.at(word>>1)[(word&1)*2+k]=data;
                }
                --wremaining;++windex;
            }
            if(d.readdatavalid){--remaining;++index;}
        }
        if(s){d.clk_source=!d.clk_source;ns+=twelve?31921:19861;}
        if(m){d.clk_mem=!d.clk_mem;nm+=7692;}
        if(v){d.clk_tv=!d.clk_tv;nt+=18518;}
        d.eval();
        if(sr&&!d.reset_source) {
            if(d.native_frame) {
                ++native_frames;
                if(acquired && source_ticks!=uint64_t(totalx*totaly))fail("native frame period changed");
                // After reset the first native row has not yet been prefetched.
                // Check complete steady frames after one native blanking interval.
                acquired=actual_mode<0 || native_frames>1;source_ticks=0;
            }
            if(acquired) {
                auto phase=source_ticks%(totalx*totaly);unsigned x=phase%totalx,y=phase/totalx;
                bool active=x<unsigned(w)&&y<unsigned(h);
                if(bool(d.native_de)!=active || bool(d.native_line)!=(x==0&&y<unsigned(h)) ||
                   bool(d.native_frame)!=(phase==0) || !d.native_ce || d.native_width!=w || d.native_height!=h)
                    fail("native marker, CE, metadata or DE latency mismatch");
                if(active) {
                    if(!drawing && d.native_rgb!=expected(x,y)) {
                        std::cerr<<"pixel x="<<x<<" y="<<y<<" mode="<<actual_mode
                                 <<" expected="<<expected(x,y)<<" actual="<<d.native_rgb<<std::endl;
                        fail("native VRAM/CLUT pixel mismatch");
                    }
                    ++source_pixels;
                }
                ++source_ticks;
            }
        }
        if(vr&&!d.reset_tv) {
            if(tag&(1u<<22)){
                ++pairs;if(d.published>(actual_mode>=0?2u:0u))seen_picture=true;
                candidates.clear();for(unsigned i=0;i<completed.size();i++)candidates.push_back(i);
            }
            if(tag&(1u<<25)) {
                int x=(tag>>9)&1023,y=tag&511;
                bool inside=x>=(640-w)/2&&x<(640+w)/2&&y>=(480-h)/2&&y<(480+h)/2;
                if(seen_picture && drawing) {
                    if(inside) {
                        unsigned pos=(y-(480-h)/2)*w+x-(640-w)/2;
                        candidates.erase(std::remove_if(candidates.begin(),candidates.end(),
                            [&](unsigned i){return completed[i][pos]!=d.rgb_raw;}),candidates.end());
                        if(candidates.empty())fail("TV image differs from every complete raw native frame within pair");
                    } else if(d.rgb_raw)fail("drawing canvas border mismatch");
                } else if(seen_picture && d.rgb_raw!=(inside?expected(x-(640-w)/2,y-(480-h)/2):0u))fail("native canvas pixel or border mismatch");
                if(seen_picture && (tag&(1u<<24)))++tv_pixels;
            }
        }
    }
    if(d.overflows||d.underruns||d.published<4||tv_pixels<1000000)fail("native coverage or buffer faults");
    std::cout<<"PASS V8 "<<w<<"x"<<h<<(actual_mode>=0?" real VRAM+Ariel bpp="+std::to_string(1<<actual_mode):pattern?" XOR":" VRAM")<<" source_pixels="<<source_pixels<<" canvas_pixels="<<tv_pixels
             <<" published="<<d.published<<" overflow="<<d.overflows<<" underrun="<<d.underruns<<std::endl;
    if(drawing)std::cout<<"PASS live drawing writes="<<draw_words<<" complete source snapshots="<<completed.size()<<" both-field frame identity"<<std::endl;
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
    if(argc>1 && std::string(argv[1])=="--direct-only") {
        try{run(true,false,4);}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<std::endl;return 1;}
        return 0;
    }
    try{run(true);run(false);run(true,false);run(false,false);tap(2,true);tap(6,true);tap(1,false);
        for(int mode=0;mode<4;mode++){run(true,false,mode);run(false,false,mode);}
        run(true,false,4);
        for(int mode : {0,2,3}){run(true,false,mode,true);run(false,false,mode,true);}
        run(true,false,4,true);}
    catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<std::endl;return 1;}
}
