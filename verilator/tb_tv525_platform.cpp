// Public-port test of startup/loss-of-lock and the continuously driven raster.
#include "Vtv525_platform.h"
#include "verilated.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>
int main(int argc,char**argv) try {
    Verilated::commandArgs(argc,argv);
    Vtv525_platform d;
    uint64_t time=0,edges=0;
    auto fail=[&](const char* message) {throw std::runtime_error(std::string(message)+" at TV edge "+std::to_string(edges));};
    auto tick=[&]() {
        ++time;bool tv=time%5==0,sys=time%3==1;
        bool rising=tv&&!d.clk_tv;
        if(tv)d.clk_tv=!d.clk_tv;
        if(sys)d.clk_sys=!d.clk_sys;
        d.eval();if(rising)++edges;return rising;
    };
    auto wait=[&](unsigned n){uint64_t end=edges+n;while(edges<end)tick();};
    d.clk_sys=0;d.clk_tv=0;d.pll_locked=0;d.video_disable=0;d.av_dis=0;d.eval();
    wait(10);if(d.drive_enable||!d.csync_n||d.picture_de)fail("startup while unlocked");
    std::vector<uint8_t> sync(900900,1);
    for(unsigned t=0;t<sync.size();++t) if(t%1716<127)sync[t]=0;
    for(unsigned origin:{0u,450450u}) {
        for(unsigned t=origin;t<origin+15444;++t)sync[t]=1;
        for(unsigned p=0;p<18;++p)for(unsigned t=0;t<(p>=6&&p<12?731u:62u);++t)sync[origin+p*858+t]=0;
    }
    uint64_t samples=0;
    for(unsigned trial=0;trial<3;++trial) {
        d.pll_locked=1;d.eval();
        if(d.drive_enable)fail("drive before synchronized startup");
        wait(2);if(d.drive_enable)fail("drive before third startup edge");
        wait(1);if(!d.drive_enable)fail("drive missing at third startup edge");
        // First pipeline-emitted pulse establishes tick zero independently.
        while(d.csync_n)tick();
        for(unsigned t=0;t<1801800;++t) {
            if(t) {do {} while(!tick());}
            unsigned phase=t%900900,line=phase/1716+1,h=phase%1716;
            bool de=((line>=23&&line<=262)||(line>=285&&line<=524))&&h>=253&&h<1675;
            if(d.csync_n!=sync[phase]||d.picture_de!=de||d.hs_n!=sync[phase]||d.vs_n!=1||!d.drive_enable)
                fail("independent 525-line sync/DE reference");
            // Independently reconstruct the default grid/circle image at the
            // emitted raster position. This catches a color/tag latency split
            // when adding a final pin register (including at aperture edges).
            int r=0,g=0,b=0;
            if(de) {
                unsigned x=(h-253)*640/1422;
                // Electrical field 1 carries odd rows, field 2 even rows.
                unsigned y=phase<450450 ? (line-23)*2+1 : (line-285)*2;
                r=g=b=16;
                if(x%32==0||y%32==0)r=g=b=96;
                int dx=int(x)-320,dy=int(y)-240,rr=dx*dx+dy*dy;
                if(rr>=25344&&rr<=25856)r=g=b=255;
                if(x==320||y==240){r=g=255;b=0;}
                if(x<2||x>=638||y<2||y>=478){r=b=0;g=255;}
            }
            unsigned pr=(32768+128*r-106*g-21*b)/256;
            unsigned lum=(77*r+150*g+29*b)/256;
            unsigned pb=(32768-42*r-85*g+128*b)/256;
            if(((d.dac_r<<2)|d.low_r)!=pr||((d.dac_g<<2)|d.low_g)!=lum||
               ((d.dac_b<<2)|d.low_b)!=pb)fail("independent color/sync alignment");
            ++samples;
        }
        d.av_dis=1;d.eval();if(d.drive_enable)fail("immediate analog disable");
        wait(19);d.av_dis=0;d.eval();if(!d.drive_enable)fail("analog reenable");
        d.video_disable=1;wait(4);
        if(!d.hs_n||d.dac_r!=32||d.low_r||d.dac_g||d.low_g||d.dac_b!=32||d.low_b)
            fail("synchronized video disable");
        d.video_disable=0;wait(4);
        // Lose lock between edges, including while TV clock is stopped.
        d.pll_locked=0;d.eval();if(d.drive_enable)fail("immediate lock-loss disable");
        d.clk_tv=0;d.clk_sys=0;d.eval();
        // Both async-reset chains assert without requiring a clock edge.
        if(d.drive_enable)fail("stopped clock drive");
        // Lock returning without any TV edge must not enable stale output.
        d.pll_locked=1;d.eval();if(d.drive_enable)fail("stopped-clock relock drive");
        d.pll_locked=0;d.eval();
        wait(13+trial*17);
        if(!d.csync_n||d.picture_de||d.osd_status)fail("lock-loss stream reset");
    }
    std::cout<<"PASS: "<<samples<<" independent sync/DE/color sample checks; three lock/relock sequences; startup, stopped-clock lock loss/relock, analog disable, synchronized video disable.\n";
}catch(const std::exception&e){std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}
