#include "Vtv_frame_pipeline.h"
#include "verilated.h"
#include <array>
#include <vector>
#include <deque>
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

using Word=std::array<uint32_t,4>;
#ifndef TV_FRAME_FILTER
#define TV_FRAME_FILTER -1
#endif
static uint32_t color(int id,int x,int y) {
    return uint32_t((id^x^y)&255)<<16 | uint32_t((x*13+y*3+id*17)&255)<<8 |
           uint32_t((y*7+x*5+id*11)&255);
}
static uint32_t display_color(int id,int x,int y,int height) {
    if(TV_FRAME_FILTER<=0)return color(id,x,y);
    uint32_t a=color(id,x,std::max(0,y-1)),c=color(id,x,y),b=color(id,x,std::min(height-1,y+1)),v=0;
    int center_weight=TV_FRAME_FILTER==1?6:2,denom=center_weight+2;
    for(int shift:{0,8,16}) {
        int sum=((a>>shift)&255)+center_weight*((c>>shift)&255)+((b>>shift)&255);
        v|=uint32_t((sum+denom/2)/denom)<<shift;
    }
    return v;
}
static uint32_t component(uint32_t rgb) {
    int r=rgb>>16,g=(rgb>>8)&255,b=rgb&255;
    auto clip=[](int v){return std::clamp(v/256,0,255);};
    return uint32_t(clip(32768+128*r-106*g-21*b))<<16 |
           uint32_t(clip(77*r+150*g+29*b))<<8 | uint32_t(clip(32768-42*r-85*g+128*b));
}
static uint32_t raster(uint64_t ticks) {
    unsigned p=ticks%900900,hs=p%1716,line=p/1716+1;
    bool odd=p<450450;unsigned fp=p%450450,half=fp/858,s=fp%858;
    bool eq=half<6||(half>=12&&half<18),broad=half>=6&&half<12;
    bool cs=!(eq?s<62:broad?s<731:hs<127);
    bool active=odd?(line>=23&&line<=262):(line>=285&&line<=524);
    bool de=active&&hs>=253&&hs<1675;
    unsigned x=de?(hs-253)*640/1422:0;
    unsigned y=de?(line-(odd?23:285))*2+(odd?1:0):0;
    bool ce=de&&(hs==253 || x!=(hs-254)*640/1422);
    return uint32_t(cs)<<28 | uint32_t(hs>=127)<<27 | uint32_t(!broad)<<26 |
           uint32_t(de)<<25 | uint32_t(ce)<<24 | uint32_t(odd)<<23 |
           uint32_t(p==0)<<22 | uint32_t(fp==0)<<21 |
           uint32_t(hs==0)<<20 | uint32_t(s==0)<<19 | x<<9 | y;
}
struct Frame { int w=0,h=0; bool valid=false; };
struct Run {
    Vtv_frame_pipeline d;
    std::vector<Word> ram=std::vector<Word>(262144);
    std::array<Frame,256> frames{};
    std::deque<std::pair<uint32_t,uint32_t>> pipe;
    uint64_t t=0, nt=111, nm=43, ns=79;
    int ht=18518, hm=5000, hs=19861;
    int sx=0,sy=0,id=1,w,h,totalx,totaly,pairs=0,pair_id=0;
    int write_remaining=0, read_remaining=0, read_index=0, read_delay=0;
    uint32_t write_base=0,read_base=0;
    uint32_t rng=0x98a723;
    uint64_t logical=0,samples=0,memory_beats=0;
    int pair_pixels=0,full_pairs=0,black_lines=0,read_slot=-1;
    bool stress=false,paused=false,cur_valid=true,line_black=false,source_enable=true;
    bool mode_change=false,ce_divide=false;
    int source_edges=0;
    uint32_t previous_tag=0;
    explicit Run(int width,int height,bool faults=false): w(width),h(height),stress(faults) {
        totalx=w==640?800:640; totaly=h==480?525:h==384?407:370;
        hs=h==384?31921:h==342?33333:19861;
        d.source_width=w; d.source_height=h; d.source_ce=1;
        d.reset_tv=1; d.source_reset=1;
        frames[id]={w,h,true};
    }
    uint32_t random(){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}
    void fail(const std::string& s){throw std::runtime_error(s+" at ps="+std::to_string(t)+" geometry="+std::to_string(w)+"x"+std::to_string(h)+" pair="+std::to_string(pairs));}
    Word load(uint32_t addr) {
        if(addr>=0x2180000 && addr<0x21c0000) return ram.at(addr-0x2180000);
        if(addr>=0x2000000 && addr<0x2001000) return Word{addr,addr^0x1234,addr^0xabcd,addr^0x9876};
        fail("memory address outside audited reservation"); return {};
    }
    void memory_before() {
        // Random backpressure and nonuniform read latency. Stress adds a
        // 1ms outage, crossing writes, line deadlines and FIFO capacity.
        bool outage=stress && t>105000000000ULL && t<106000000000ULL;
        d.waitrequest=outage || ((random()&15)==0);
        d.readdatavalid=0;
        if(read_remaining && !outage) {
            if(read_delay) --read_delay;
            else if((random()&3)!=0) {
                Word v=load(read_base+read_index);
                for(int k=0;k<4;k++)d.readdata[k]=v[k];
                d.readdatavalid=1;
            }
        }
        // ASCAL-like competing reader: 16 beats repeatedly. Independent
        // address range and oracle make response misrouting observable.
        d.a_read = !paused && pairs>=1;
        d.a_write=0; d.a_address=0x2000000; d.a_burstcount=16; d.a_byteenable=65535;
    }
    int a_count=0;
    void memory_accept() {
        if(d.a_readdatavalid) {
            Word expected=load(0x2000000+a_count);
            for(int k=0;k<4;k++)if(d.a_readdata[k]!=expected[k])fail("arbiter response delivered to wrong reader");
            a_count=(a_count+1)%16;
        }
        if(d.read && !d.waitrequest) {
            if(read_remaining || write_remaining)fail("overlapping memory transactions");
            read_base=d.address; read_remaining=d.burstcount;read_index=0;read_delay=10+random()%91;
            if(read_base>=0x2180000) {
                int slot=(read_base-0x2180000)/76800;
                if(read_slot>=0 && read_slot!=slot)fail("frame descriptor changed within pair");
                read_slot=slot;
            }
        }
        if(d.write && !d.waitrequest) {
            if(read_remaining)fail("write while read outstanding");
            if(!write_remaining) {write_base=d.address;write_remaining=d.burstcount;}
            uint32_t addr=write_base+d.burstcount-write_remaining;
            if(addr>=0x2180000 && d.byteenable) {
                int slot=(addr-0x2180000)/76800;
                if(slot==read_slot)fail("writer overwrote DISPLAYING frame");
                Word &v=ram.at(addr-0x2180000);
                for(int k=0;k<4;k++)for(int b=0;b<4;b++)if(d.byteenable&(1<<(k*4+b))) {
                    uint32_t mask=255u<<(b*8);v[k]=(v[k]&~mask)|(d.writedata[k]&mask);
                }
            }
            --write_remaining; ++memory_beats;
        }
        if(d.readdatavalid) {--read_remaining;++read_index;}
    }
    void source_before() {
        source_enable=!ce_divide || ((source_edges++&1)==0);
        bool source_loss=stress && t>175000000000ULL && t<215000000000ULL;
        bool resetting=stress && t>140000000000ULL && t<140050000000ULL;
        d.source_reset=t<1000000 || resetting;
        d.inhibit=resetting;
        if(resetting || source_loss)cur_valid=false;
        d.source_ce=source_enable;
        d.source_de=sx<w && sy<h && !source_loss;
        // A dropped input pixel invalidates the WHOLE frame.
        if(stress && id==5 && sy==77 && sx==100) {d.source_de=0;cur_valid=false;}
        d.source_line=d.source_de && sx==0;
        d.source_frame=d.source_line && sy==0;
        d.source_rgb=color(id,sx,sy);
    }
    void source_after() {
        if(!source_enable)return;
        if(sx==w && sy==h-1)frames[id].valid=cur_valid;
        if(++sx==totalx) {sx=0;if(++sy==totaly) {
            sy=0;++id;cur_valid=true;
            if(mode_change && id==8) { w=512;h=384;totalx=640;totaly=407;hs=31921;d.source_width=w;d.source_height=h; }
            frames[id]={w,h,true};
        }}
    }
    void tv_before() { d.reset_tv=t<1000000; }
    void tv_after(uint32_t raw_before) {
        if(d.reset_tv) {pipe.clear();previous_tag=0;return;}
        if(raw_before!=raster(samples))fail("independent TV raster/phase mismatch");
        // Canvas RAM adds one stage; OSD + converter add five. Compare all
        // controls, every repeated DAC sample, and conversion independently.
        if(pipe.size()==5) {
            auto expected=pipe.front();pipe.pop_front();
            if(d.tag_out!=expected.first)fail("pixel/control pipeline latency mismatch");
            if(d.component!=component(expected.second))fail("component pixel pipeline mismatch");
        }
        pipe.push_back({raw_before,d.rgb_raw});
        uint32_t tag=raw_before;previous_tag=raw_before;
        ++samples;
        if(tag&(1u<<22)) {
            if(pair_id && pair_pixels==307200) ++full_pairs;
            ++pairs;pair_id=0;pair_pixels=0;read_slot=-1;
        }
        if(!(tag&(1u<<25)))return;
        int x=(tag>>9)&1023,y=tag&511;
        int ox=(640-w)/2,oy=(480-h)/2;
        if(pair_id) {ox=(640-frames[pair_id].w)/2;oy=(480-frames[pair_id].h)/2;}
        int pw=pair_id?frames[pair_id].w:w,ph=pair_id?frames[pair_id].h:h;
        bool inside=x>=ox&&x<ox+pw&&y>=oy&&y<oy+ph;
        uint32_t rgb=d.rgb_raw;
        if((tag&(1u<<24))) {++logical;++pair_pixels;}
        if(x==0 && (tag&(1u<<24)))line_black=false;
        if(!pair_id && rgb) {
            for(int candidate=1;candidate<id+1;candidate++) {
                auto f=frames[candidate];int cx=x-(640-f.w)/2,cy=y-(480-f.h)/2;
                if(f.valid && cx>=0 && cy>=0 && cx<f.w && cy<f.h && rgb==display_color(candidate,cx,cy,f.h)) {
                    pair_id=candidate;ox=(640-f.w)/2;oy=(480-f.h)/2;inside=true;break;
                }
            }
            if(!pair_id)fail("displayed incomplete or invalid frame");
        }
        if(pair_id) {
            uint32_t expected=inside?display_color(pair_id,x-ox,y-oy,frames[pair_id].h):0;
            if(stress && inside && x==ox && rgb==0) {line_black=true;++black_lines;}
            if(line_black)expected=0;
            if(rgb!=expected)fail("pixel mismatch x="+std::to_string(x)+" y="+std::to_string(y)+" id="+std::to_string(pair_id)+" actual="+std::to_string(rgb)+" expected="+std::to_string(expected));
        } else if(rgb)fail("unexpected diagnostic pixel");
    }
    void run(int target_pairs=9) {
        d.eval();
        while(pairs<target_pairs) {
            t=std::min({nt,nm,ns});
            bool tv=t==nt,mem=t==nm,src=t==ns;
            bool tv_r=tv&&!d.clk_tv,mem_r=mem&&!d.clk_mem,src_r=src&&!d.clk_source;
            if(mem_r)memory_before();
            if(src_r)source_before();
            if(tv_r)tv_before();
            d.eval();
            uint32_t raw=d.tag_raw;
            if(mem_r)memory_accept();
            if(tv){d.clk_tv=!d.clk_tv;nt+=ht;}
            if(mem){d.clk_mem=!d.clk_mem;nm+=hm;}
            if(src){d.clk_source=!d.clk_source;ns+=hs;}
            d.eval();
            if(tv_r)tv_after(raw);
            if(src_r)source_after();
        }
        std::cout<<"PASS "<<w<<"x"<<h<<(stress?" faults":" healthy")<<" samples="<<samples
                 <<" logical="<<logical<<" full_pairs="<<full_pairs<<" published="<<d.published
                 <<" dropped="<<d.dropped<<" repeated="<<d.repeated<<" overflow="<<d.overflows
                 <<" underrun="<<d.underruns<<" black_lines="<<black_lines<<std::endl;
        if(full_pairs<4)fail("insufficient full woven frame coverage");
        if(!stress && (d.overflows || d.underruns))fail("healthy DDR service produced video faults");
        if(stress && (!d.overflows || !d.underruns || !d.dropped))fail("stress faults not exercised");
    }
};
int main(int argc,char**argv) {
    Verilated::commandArgs(argc,argv);
    try {
        Run(512,342).run(); Run(512,384).run(); Run(640,480).run();
        Run(640,480,true).run(10);
        Run modes(640,480);modes.mode_change=true;modes.run(10);
        Run ce(512,342);ce.ce_divide=true;ce.hs=16666;ce.ns=9001;ce.nm=500;ce.nt=700;ce.run();
    } catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<std::endl;return 1;}
}
