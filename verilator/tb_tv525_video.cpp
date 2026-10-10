#include "Vtv525_video.h"
#include "verilated.h"
#include <iostream>
#include <stdexcept>

int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);
    Vtv525_video t;
    t.clk_tv=0; t.clk_mem=0; t.clk_source=0;
    t.reset_tv=1; t.source_reset=1; t.inhibit=0;
    t.source_ce=0; t.source_de=0; t.source_line=0; t.source_frame=0;
    t.source_width=640; t.source_height=480; t.source_rgb=0;
    t.waitrequest=0; t.readdatavalid=0;
    for (int i=0;i<4;++i) t.readdata[i]=0;
    auto tick=[&]() {t.clk_tv=0;t.clk_mem=0;t.eval();t.clk_tv=1;t.clk_mem=1;t.eval();};
    tick(); tick(); t.reset_tv=0;
    unsigned active=0,odd=0,even=0;
    for (unsigned n=0;n<1801800;++n) {
        // Guest reset cannot restart the independent electrical raster.
        t.source_reset=(n%900900)<300000;
        tick();
        unsigned p=n%900900,h=p%1716,line=p/1716,half=(p%450450)/858;
        bool field=p<450450;
        bool de=(field?(line>=22&&line<262):(line>=284&&line<524))&&h>=253&&h<1675;
        if (t.hs!=(h>=127) || t.vs!=!(half>=6&&half<12) || t.de!=de || t.field_id!=field || t.rgb!=0) {
            std::cerr<<"RGB/sync/parity mismatch at sample "<<n<<'\n';return 1;
        }
        if (de) {++active;if(field)++odd;else++even;}
    }
    if (odd!=682560 || even!=682560) return 1;
    std::cout<<"PASS standard RGB raster: 1801800 samples, "<<active<<" active samples, both fields, guest reset isolation\n";
}
