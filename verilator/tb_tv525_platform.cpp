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
        // First pipeline-emitted pulse establishes tick zero independently.
        while(d.csync_n)tick();
        for(unsigned t=0;t<1801800;++t) {
            if(t) {do {} while(!tick());}
            unsigned phase=t%900900,line=phase/1716+1,h=phase%1716;
            bool de=((line>=23&&line<=262)||(line>=285&&line<=524))&&h>=253&&h<1675;
            if(d.csync_n!=sync[phase]||d.picture_de!=de||d.hs_n!=sync[phase]||d.vs_n!=1||!d.drive_enable)
                fail("independent 525-line sync/DE reference");
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
        wait(13+trial*17);
        if(!d.csync_n||d.picture_de||d.osd_status)fail("lock-loss stream reset");
    }
    std::cout<<"PASS: "<<samples<<" independent sync/DE sample checks; three lock/relock sequences; startup, stopped-clock lock loss, analog disable, synchronized video disable.\n";
}catch(const std::exception&e){std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}
