// End-to-end oracle uses public canvas tags and an independently populated
// host bitmap. Clocks have different periods/phases; no internal DUT reads.
#include "Vtv525_output.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
namespace fs=std::filesystem;
constexpr uint32_t idle=7u<<26;
uint32_t component(uint32_t rgb,bool de) {
    int r=de ? (rgb>>16)&255 : 0,g=de ? (rgb>>8)&255 : 0,b=de ? rgb&255 : 0;
    return ((32768+128*r-106*g-21*b)/256<<16) |
           ((77*r+150*g+29*b)/256<<8) | (32768-42*r-85*g+128*b)/256;
}
struct Config { bool enable=false,info=false,high=false; int x=0,y=0,w=256,h=64,rot=0; };
struct Sample { uint32_t rgb=0,tag=idle; bool verify=false; uint32_t source=0; };
class Bench {
public:
    Vtv525_output dut;
    std::array<uint8_t,4096> bitmap{};
    Config cfg;
    std::array<Sample,5> delay{};
    std::array<Sample,3> conversion_delay{};
    Config transition_old,transition_new;
    bool monitor_transition=false;
    unsigned transition_mask=3;
    uint64_t time=0,tv_edges=0,sys_edges=0,checks=0,verified=0;
    bool verify=false,capture=false;
    std::vector<uint32_t> image=std::vector<uint32_t>(640*480);
    std::array<unsigned,2> field_pixels{};
    uint32_t compose(uint32_t rgb,uint32_t tag) {
        if(!cfg.enable || !(tag&(1u<<25))) return rgb;
        int x=(tag>>9)&1023,y=tag&511;
        int w=cfg.info ? std::min(cfg.w,256) : 256;
        int h=cfg.info ? std::min(cfg.h,128) : cfg.high ? 128 : 64;
        int dw=cfg.rot%2 ? h : w,dh=cfg.rot%2 ? w : h;
        int ox=cfg.info ? cfg.x*2 : (640-dw*2)/2;
        int oy=cfg.info ? cfg.y*2 : std::max(0,(480-dh*2)/2);
        if(x<ox || x>=ox+2*dw || y<oy || y>=oy+2*dh) return rgb;
        int u=(x-ox)/2,v=(y-oy)/2,sx=0,sy=0;
        switch(cfg.rot) {
            case 0: sx=u;sy=v;break;
            case 1: sx=v;sy=h-1-u;break;
            case 2: sx=w-1-u;sy=h-1-v;break;
            case 3: sx=w-1-v;sy=u;break;
        }
        bool pixel=(bitmap[(sy/8)*256+sx]>>(sy%8))&1;
        int r=((rgb>>16)&255)/8,g=((rgb>>8)&255)/8,b=(rgb&255)/8;
        return ((r+32+(pixel?192:0))<<16)|((g+(pixel?192:0))<<8)|(b+(pixel?192:0));
    }
    void tick() {
        ++time;
        bool tv_toggle=time%5==0,sys_toggle=time%7==2;
        bool tv_rise=tv_toggle && !dut.clk_tv;
        bool sys_rise=sys_toggle && !dut.clk_sys;
        Sample incoming;
        Sample converter_input;
        if(tv_rise) {
            incoming={compose(dut.rgb_raw,dut.tag_raw),dut.tag_raw,verify,dut.rgb_raw};
            converter_input={dut.composed_rgb,dut.tag_composed,false,0};
        }
        if(tv_toggle) dut.clk_tv=!dut.clk_tv;
        if(sys_toggle) dut.clk_sys=!dut.clk_sys;
        dut.eval();
        if(sys_rise) ++sys_edges;
        if(!tv_rise) return;
        ++tv_edges;
        if(dut.reset_tv) delay.fill({0,idle,false});
        else { for(int i=4;i>0;--i) delay[i]=delay[i-1]; delay[0]=incoming; }
        if(dut.reset_tv) conversion_delay.fill({0,idle,false});
        else {
            conversion_delay[2]=conversion_delay[1];conversion_delay[1]=conversion_delay[0];
            conversion_delay[0]=converter_input;
        }
        const auto& osd=delay[1]; const auto& out=delay[4];
        if(dut.tag_composed!=osd.tag || dut.tag_out!=out.tag)
            fail("sample control latency");
        if(osd.verify && dut.composed_rgb!=osd.rgb) fail("OSD bitmap/coordinates");
        // Across config changes, every pixel in an entire field pair must
        // belong to one complete old/new config. Reject intermediate tuples.
        if(monitor_transition) {
            if(osd.tag&(1u<<22)) transition_mask=3;
            Config saved=cfg;
            cfg=transition_old;uint32_t old_rgb=compose(osd.source,osd.tag);
            cfg=transition_new;uint32_t new_rgb=compose(osd.source,osd.tag);cfg=saved;
            if(dut.composed_rgb!=old_rgb) transition_mask&=~1u;
            if(dut.composed_rgb!=new_rgb) transition_mask&=~2u;
            if(!transition_mask) fail("torn OSD config within a field pair");
        }
        const auto& converted=conversion_delay[2];
        if(dut.component!=component(converted.rgb,(converted.tag>>25)&1))
            fail("component pipeline");
        uint32_t pin_code=dut.video_disable ? 0x800080 : dut.component;
        if(((dut.dac_r<<2)|dut.low_r)!=((pin_code>>16)&255) ||
           ((dut.dac_g<<2)|dut.low_g)!=((pin_code>>8)&255) ||
           ((dut.dac_b<<2)|dut.low_b)!=(pin_code&255) ||
           dut.drive_enable==dut.av_dis || dut.vs_n!=1 ||
           dut.hs_n!=(dut.video_disable || ((out.tag>>28)&1))) fail("digital DAC lane/sync route");
        ++checks;
        if(out.verify) ++verified;
        if(capture && out.verify && (out.tag&(1u<<24))) {
            unsigned x=(out.tag>>9)&1023,y=out.tag&511;
            image[y*640+x]=out.rgb;
            ++field_pixels[(out.tag>>23)&1];
        }
    }
    [[noreturn]] void fail(const std::string& msg) {
        throw std::runtime_error(msg+" at TV edge "+std::to_string(tv_edges));
    }
    void sys_wait(unsigned n) { uint64_t target=sys_edges+n;while(sys_edges<target) tick(); }
    void tv_wait(unsigned n) { uint64_t target=tv_edges+n;while(tv_edges<target) tick(); }
    void begin() { dut.io_osd=1;dut.io_strobe=0;sys_wait(3); }
    void word(unsigned value) {
        dut.io_din=value;dut.io_strobe=0;sys_wait(2);
        dut.io_strobe=1;sys_wait(2);dut.io_strobe=0;sys_wait(2);
    }
    void end() { dut.io_osd=0;sys_wait(3); }
    void set_config(const Config& c) {
        begin();word(c.enable ? (c.info?0x45:0x41) : 0x40);
        word(c.x);word(c.y);word(c.w/8);word(c.h/8);word(c.rot);end();
    }
    void frame_boundary() {
        // Raw frame marker before the sampling edge. Consume its first edge.
        while(!(dut.tag_raw&(1u<<22))) tick();
        tv_wait(1);
    }
    void settle() { verify=false;for(int n=0;n<3;++n) { tv_wait(10);frame_boundary(); }tv_wait(10); }
    void run_frame(const fs::path& out,const std::string& name) {
        verify=false;frame_boundary();tv_wait(10);frame_boundary();
        verify=true;capture=true;field_pixels.fill(0);
        // Marker already consumed; first active sample is much later.
        tv_wait(900900);capture=false;
        if(field_pixels[0]!=153600 || field_pixels[1]!=153600) fail("field pixel coverage");
        std::ofstream f(out/(name+".ppm"),std::ios::binary);
        f<<"P6\n640 480\n255\n";
        for(uint32_t rgb:image) { char p[3]={char(rgb>>16),char(rgb>>8),char(rgb)};f.write(p,3); }
        verify=false;
    }
};
int main(int argc,char** argv) try {
    Verilated::commandArgs(argc,argv);
    fs::path out=argc>1?argv[1]:"out/tv525_stage2";fs::create_directories(out);
    Bench b;
    b.dut.clk_tv=0;b.dut.clk_sys=0;b.dut.reset_tv=1;b.dut.reset_sys=1;
    b.dut.eval();b.sys_wait(8);b.dut.reset_tv=0;b.dut.reset_sys=0;b.tv_wait(5);
    // Populate each page over the actual host protocol. Asymmetric row/column
    // signatures and readable 5x7 text expose rotations and field parity.
    for(int y=0;y<128;++y) for(int x=0;x<256;++x) {
        bool on=(x==0 || x==255 || y==0 || y==127 || (x%31==0 && y%13<4));
        if(on) b.bitmap[(y/8)*256+x]|=1u<<(y%8);
    }
    const std::array<std::array<uint8_t,7>,5> font={{
        {31,4,4,4,4,4,4}, {17,17,17,17,17,10,4},
        {17,17,17,31,1,1,1}, {14,17,17,14,17,17,14}, {14,17,19,21,25,17,14}}};
    for(int c=0;c<5;++c) for(int y=0;y<7;++y) for(int x=0;x<5;++x)
        if((font[c][y]>>(4-x))&1) for(int dy=0;dy<3;++dy) for(int dx=0;dx<3;++dx) {
            int sx=76+c*21+x*3+dx,sy=20+y*3+dy;
            b.bitmap[(sy/8)*256+sx]|=1u<<(sy%8);
        }
    for(unsigned page=0;page<16;++page) {
        b.begin();b.word(0x20+page);
        for(unsigned x=0;x<256;++x) b.word(b.bitmap[page*256+x]);
        b.end();
    }
    b.dut.pattern=4;b.dut.geometry=2;
    b.cfg={false,false,true,0,0,256,128,0}; b.set_config(b.cfg); b.settle();
    b.run_frame(out,"disabled_grid_342");
    // Enabling high-res was carried by write page 8. It remains set until disable.
    // The above disable cleared it; reassert it through a high-res page write.
    b.begin();b.word(0x28);b.word(b.bitmap[8*256]);b.end();
    b.cfg={true,false,true,0,0,256,128,0};b.set_config(b.cfg);b.settle();
    b.run_frame(out,"menu_grid_342");
    // Start a control transaction shortly before a pair boundary, hold it
    // open across the boundary, then complete its parameters. Publishing
    // host_config during the transaction would expose a partial tuple.
    b.transition_old=b.cfg;b.transition_new={true,true,true,15,19,128,80,3};
    b.monitor_transition=true;b.transition_mask=3;
    b.frame_boundary();b.tv_wait(900000);b.begin();b.word(0x45);b.tv_wait(1000);
    b.word(15);b.word(19);b.word(16);b.word(10);b.word(3);b.end();
    b.cfg=b.transition_new;b.settle();b.monitor_transition=false;
    b.run_frame(out,"transaction_across_pair");
    for(int rot=0;rot<4;++rot) {
        b.cfg={true,true,true,7,9,160,96,rot};b.set_config(b.cfg);b.settle();
        b.dut.pattern=0;b.dut.geometry=0;
        b.run_frame(out,"info_black_rot"+std::to_string(rot));
    }
    // Multiple changes while previous payload awaits a frame acknowledgement:
    // final config must eventually arrive intact, including every dimension.
    b.set_config({true,true,true,12,15,64,32,1});
    b.cfg={true,true,true,280,210,80,64,2};b.set_config(b.cfg);b.settle();
    b.run_frame(out,"info_clipped");
    b.cfg={false,false,false,0,0,256,64,0};b.set_config(b.cfg);b.settle();
    b.cfg.enable=true;b.set_config(b.cfg);b.settle();
    b.dut.pattern=3;b.dut.geometry=1;b.run_frame(out,"lowres_menu_bars_384");
    if(!b.dut.osd_status) b.fail("menu status");
    b.dut.video_disable=1;b.tv_wait(997);b.dut.av_dis=1;b.tv_wait(999);
    b.dut.video_disable=0;b.tv_wait(173);b.dut.av_dis=0;
    // Reset in active scanout and with a pending host configuration. RAM stays
    // intact, but both handshake endpoints reset and OSD becomes disabled.
    b.set_config({true,true,false,1,1,16,16,3});
    b.dut.reset_tv=1;b.dut.reset_sys=1;b.sys_wait(9);
    b.dut.reset_tv=0;b.dut.reset_sys=0;b.cfg={};b.settle();
    b.dut.pattern=1;b.dut.geometry=0;b.run_frame(out,"reset_white");
    std::string result="PASS: asynchronous TV/host clocks; 4096 protocol bitmap bytes; "
        "both fields; menu low/high resolution; all info rotations; clipping; "
        "queued config updates and transaction across pair boundary; absent Mac input; reset and digital pin disables.\n";
    result+=std::to_string(b.checks)+" tag/pin checks, "+std::to_string(b.verified)+" independently composed component samples.\n";
    std::cout<<result;std::ofstream(out/"verification.txt")<<result;
} catch(const std::exception& e) { std::cerr<<"FAIL: "<<e.what()<<"\n";return 1; }
