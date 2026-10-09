#include "Vtv_deflicker_capture.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>
struct Bench {
    Vtv_deflicker_capture d;
    std::vector<uint32_t> expected;
    uint64_t checked=0;
    unsigned cursor=0, starts=0, ends=0, aborts=0, clocks=0;
    bool verify=true, gap=false;
    void fail(const char* s) {throw std::runtime_error(std::string(s)+" pixel="+std::to_string(cursor));}
    void tick(bool enabled) {
        d.clk=0; d.ce=enabled; d.eval();
        if(d.filtered_reset) ++aborts;
        if(d.push) {
            unsigned flags=d.data[4];
            if(flags&32) {
                if(flags&16) {cursor=0;++starts;}
                else if(flags&8) {
                    if(flags&4) fail("capture marked filtered image bad");
                    if(verify && cursor!=expected.size()) fail("incomplete filtered image");
                    ++ends;
                }
            } else if(verify) {
                for(unsigned k=0;k<4;++k) {
                    if(cursor>=expected.size() || d.data[k]!=(expected[cursor]&0xffffff))
                        throw std::runtime_error("filtered quartet pixel="+std::to_string(cursor)+
                            " actual="+std::to_string(d.data[k])+" expected="+std::to_string(expected.at(cursor)));
                    ++cursor; ++checked;
                }
            }
        }
        d.clk=1;d.eval();++clocks;
    }
    void sample() {
        // Variable CE gaps also leave sufficient opportunities to commit RAM.
        if(gap) for(unsigned i=0;i<1+(clocks%3);++i) tick(false);
        tick(true);
    }
    void blank(unsigned n) {d.de=0;d.line_start=0;d.frame_start=0;while(n--)sample();}
    static uint32_t pixel(int pattern,int x,int y) {
        if(pattern==0) return ((x^y)&1)?0xffffff:0;
        if(pattern==1) return 0x37a5f1;
        if(pattern==2) return y==117?0xffffff:0;
        return ((x*17+y*31)&255)<<16 | ((x*3+y*7)&255)<<8 | ((x^y*11)&255);
    }
    void frame(int w,int h,int mode,int pattern,bool gaps) {
        gap=gaps;d.width=w;d.height=h;d.mode=mode;
        expected.clear();expected.reserve(w*h);
        for(int y=0;y<h;++y)for(int x=0;x<w;++x) {
            uint32_t a=pixel(pattern,x,std::max(0,y-1)),c=pixel(pattern,x,y),
                     b=pixel(pattern,x,std::min(h-1,y+1)),v=0;
            for(int shift:{0,8,16}) {
                int av=(a>>shift)&255,cv=(c>>shift)&255,bv=(b>>shift)&255;
                int out=mode==0?cv:mode==1?(av+6*cv+bv+4)/8:(av+2*cv+bv+2)/4;
                v|=uint32_t(out)<<shift;
            }
            expected.push_back(v);
        }
        unsigned old_end=ends,old_start=starts,old_abort=aborts;
        for(int y=0;y<h;++y) {
            // Change the live setting midframe: the expected mode stays fixed.
            if(y==h/2)d.mode=(mode+1)%3;
            for(int x=0;x<w;++x) {
                d.de=1;d.line_start=x==0;d.frame_start=x==0&&y==0;
                d.rgb=pixel(pattern,x,y);sample();
            }
            blank(32);
        }
        blank(w+8);
        if(ends!=old_end+1 || starts!=old_start+1 || aborts!=old_abort)
            fail("frame publication or unexpected abort");
    }
};
int main(int argc,char**argv) try {
    Verilated::commandArgs(argc,argv);Bench b;
    b.d.reset=1;b.tick(true);b.d.reset=0;b.blank(3);
    for(auto size: {std::pair<int,int>{512,342},{512,384},{640,480}})
        for(int mode=0;mode<3;++mode)for(int pattern=0;pattern<4;++pattern)
            b.frame(size.first,size.second,mode,pattern,(mode+pattern)%2);
    // A missing pixel must abort rather than publish an apparently good frame.
    b.verify=false;b.gap=false;b.d.width=640;b.d.height=480;
    unsigned end=b.ends,aborts=b.aborts;
    for(int y=0;y<5;++y) {
        for(int x=0;x<640;++x) {
            b.d.de=!(y==3&&x==123);b.d.line_start=x==0;b.d.frame_start=x==0&&y==0;
            b.d.rgb=0xffffff;b.sample();
        }
        b.blank(10);
    }
    b.blank(650);
    if(b.ends!=end || b.aborts==aborts)b.fail("missing pixel did not abort");
    b.verify=true;b.frame(512,384,2,3,true);
    // Guest reset in active capture, followed by a clean new image.
    b.verify=false;
    for(int x=0;x<512;++x) {
        b.d.de=1;b.d.line_start=x==0;b.d.frame_start=x==0;b.sample();
    }
    b.d.reset=1;b.tick(false);b.d.reset=0;b.blank(10);
    b.verify=true;b.frame(640,480,1,0,false);
    // Unsupported portrait geometry produces no published image.
    end=b.ends;b.verify=false;b.d.width=0;b.d.height=0;
    b.d.de=1;b.d.line_start=1;b.d.frame_start=1;b.sample();b.blank(650);
    if(b.ends!=end)b.fail("unsupported geometry published");
    b.verify=true;b.frame(512,342,0,3,false);
    std::cout<<"PASS: "<<b.checked<<" exact filtered pixels through RGBx capture; "
             <<b.ends<<" complete images; all modes/geometries, checkerboard, flat color, thin line, RGB gradient, CE gaps, frame-latched mode changes, abort/reset recovery and portrait rejection.\n";
} catch(const std::exception&e) {std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}
